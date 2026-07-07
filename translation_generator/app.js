const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const TEXT_NODE_PATTERN = /(<w:t\b[^>]*>)([\s\S]*?)(<\/w:t>)/g;
const SPANISH_MONTHS = [
  "enero",
  "febrero",
  "marzo",
  "abril",
  "mayo",
  "junio",
  "julio",
  "agosto",
  "septiembre",
  "octubre",
  "noviembre",
  "diciembre",
];
const ENGLISH_MONTH_INDEX = {
  jan: 0,
  january: 0,
  feb: 1,
  february: 1,
  mar: 2,
  march: 2,
  apr: 3,
  april: 3,
  may: 4,
  jun: 5,
  june: 5,
  jul: 6,
  july: 6,
  aug: 7,
  august: 7,
  sep: 8,
  sept: 8,
  september: 8,
  oct: 9,
  october: 9,
  nov: 10,
  november: 10,
  dec: 11,
  december: 11,
};
const TYPE_OPTIONS = [
  "VISADO DE TURISTA",
  "VISADO / ESTANCIA A LARGO PLAZO",
  "FINES DE INMIGRACIÓN DISTINTOS DE LA CIUDADANÍA",
  "SOLICITUD DE CIUDADANÍA/NACIONALIDAD",
  "PERMISO DE RESIDENCIA",
  "EMPLEO / VISADO DE EMPLEO / PERMISO DE TRABAJO",
  "EDUCACIÓN / INVESTIGACIÓN",
  "VIAJAR al",
];
const TITLE_OPTIONS = ["Sr.", "Sra."];
const RELATION_OPTIONS = ["hijo de", "hija de", "mujer de"];
const REGISTRAR_OPTIONS = ["Sub Registrador", "Local Registrador", "Registrador Local (EOMC)"];

const TEMPLATE_OPTIONS = {
  "pcc-jalandhar": {
    label: "PCC Jalandhar",
    templatePath: "templates/pccjalandhar.docx",
    outputName: "pcc-jalandhar-translation",
  },
  "pcc-chandigarh": {
    label: "PCC Chandigarh",
    templatePath: "templates/pccChandigarh.docx",
    outputName: "pcc-chandigarh-translation",
  },
  medical: {
    label: "Medical",
    templatePath: "templates/MEDICAL.docx",
    outputName: "medical-translation",
  },
  birth: {
    label: "Birth",
    templatePath: "templates/BIRTH.docx",
    outputName: "birth-translation",
  },
  marriage: {
    label: "Marriage",
    templatePath: "templates/MARRIAGE.docx",
    outputName: "marriage-translation",
  },
};

const state = {
  selectedKey: "",
  templateBuffer: null,
  placeholders: [],
  lastDocxBlob: null,
};

const dom = {};

document.addEventListener("DOMContentLoaded", () => {
  cacheDom();
  populateTemplates();
  bindEvents();

  if (window.location.protocol === "file:") {
    setStatus("Run this folder through a local static server so template files can load.", "error");
  }
});

function cacheDom() {
  dom.templateSelect = document.querySelector("#templateSelect");
  dom.templateMeta = document.querySelector("#templateMeta");
  dom.entryTabs = document.querySelector("#entryTabs");
  dom.fieldForm = document.querySelector("#fieldForm");
  dom.bulkInput = document.querySelector("#bulkInput");
  dom.applyBulk = document.querySelector("#applyBulk");
  dom.clearBulk = document.querySelector("#clearBulk");
  dom.bulkResult = document.querySelector("#bulkResult");
  dom.tabButtons = Array.from(document.querySelectorAll(".tab-button"));
  dom.tabPanels = Array.from(document.querySelectorAll(".tab-panel"));
  dom.actions = document.querySelector("#actions");
  dom.status = document.querySelector("#status");
  dom.downloadDocx = document.querySelector("#downloadDocx");
  dom.downloadPdf = document.querySelector("#downloadPdf");
  dom.resetForm = document.querySelector("#resetForm");
  dom.previewShell = document.querySelector("#previewShell");
  dom.docPreview = document.querySelector("#docPreview");
  dom.previewBadge = document.querySelector("#previewBadge");
}

function populateTemplates() {
  Object.entries(TEMPLATE_OPTIONS).forEach(([key, template]) => {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = template.label;
    dom.templateSelect.append(option);
  });
}

function bindEvents() {
  dom.templateSelect.addEventListener("change", handleTemplateChange);
  dom.applyBulk.addEventListener("click", applyBulkInput);
  dom.clearBulk.addEventListener("click", clearBulkInput);
  dom.tabButtons.forEach((button) => {
    button.addEventListener("click", () => setActiveTab(button.dataset.tab));
  });
  dom.downloadDocx.addEventListener("click", handleDocxDownload);
  dom.downloadPdf.addEventListener("click", handlePdfDownload);
  dom.resetForm.addEventListener("click", clearFields);
}

async function handleTemplateChange() {
  const selectedKey = dom.templateSelect.value;
  resetTemplateState();

  if (!selectedKey) {
    dom.templateMeta.textContent = "Select a template to load its placeholders.";
    return;
  }

  const template = TEMPLATE_OPTIONS[selectedKey];
  state.selectedKey = selectedKey;
  dom.templateMeta.textContent = `${template.label} - loading placeholders from ${template.templatePath}`;
  setBusy(true);
  setStatus("Loading template...", "");

  try {
    await ensureLibraries();
    const buffer = await fetchTemplate(template.templatePath);
    const zip = await JSZip.loadAsync(buffer.slice(0));
    const placeholders = await extractPlaceholders(zip);

    if (!placeholders.length) {
      throw new Error("No <<PLACEHOLDER>> values were found in this template.");
    }

    state.templateBuffer = buffer;
    state.placeholders = placeholders;
    renderFields(getDisplayPlaceholders(placeholders));
    dom.templateMeta.textContent = `${template.label} - ${placeholders.length} placeholders loaded.`;
    setStatus("Template ready.", "success");
  } catch (error) {
    resetTemplateState();
    setStatus(error.message || "Template could not be loaded.", "error");
    dom.templateMeta.textContent = "Template load failed.";
  } finally {
    setBusy(false);
  }
}

function resetTemplateState() {
  state.templateBuffer = null;
  state.placeholders = [];
  state.lastDocxBlob = null;
  dom.fieldForm.replaceChildren();
  dom.entryTabs.hidden = true;
  dom.bulkInput.value = "";
  setBulkResult("", "");
  setActiveTab("bulk");
  dom.actions.hidden = true;
  dom.previewShell.hidden = true;
  dom.docPreview.replaceChildren();
}

async function ensureLibraries() {
  if (!window.JSZip) {
    throw new Error("JSZip failed to load. Check internet access for frontend libraries.");
  }
}

async function fetchTemplate(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Template file not found: ${path}`);
  }
  return response.arrayBuffer();
}

async function extractPlaceholders(zip) {
  const found = new Map();
  const fileNames = Object.keys(zip.files).filter((name) => name.startsWith("word/") && name.endsWith(".xml"));

  for (const fileName of fileNames) {
    const file = zip.file(fileName);
    if (!file) continue;

    const xml = await file.async("string");
    const text = getJoinedTextNodes(xml);
    const matches = text.matchAll(/<<[^<>]+>>/g);

    for (const match of matches) {
      const token = match[0];
      if (!found.has(token)) {
        found.set(token, { token, count: 0, index: found.size });
      }
      found.get(token).count += 1;
    }
  }

  return Array.from(found.values()).sort((left, right) => left.index - right.index);
}

function getJoinedTextNodes(xml) {
  return Array.from(xml.matchAll(TEXT_NODE_PATTERN), (match) => decodeXml(match[2])).join("");
}

function getDisplayPlaceholders(placeholders) {
  if (!state.selectedKey.startsWith("pcc-")) {
    return placeholders;
  }

  const ordered = placeholders.filter(({ token }) => token !== "<<NAME>>");
  const namePlaceholder = placeholders.find(({ token }) => token === "<<NAME>>");
  const titleIndex = ordered.findIndex(({ token }) => token === "<<TITLE>>");

  if (!namePlaceholder || titleIndex < 0) {
    return placeholders;
  }

  ordered.splice(titleIndex + 1, 0, namePlaceholder);
  return ordered;
}

function renderFields(placeholders) {
  const fragment = document.createDocumentFragment();

  placeholders.forEach(({ token }) => {
    const field = document.createElement("div");
    field.className = "field-card";

    const label = document.createElement("label");
    const labelText = document.createElement("span");
    labelText.textContent = humanizePlaceholder(token);

    const placeholderText = document.createElement("span");
    placeholderText.className = "placeholder-token";
    placeholderText.textContent = token;

    if (hasDropdownOptions(token)) {
      appendDropdownControl(label, token);
    } else {
      label.append(createTextarea(token));
    }

    label.prepend(labelText, placeholderText);
    field.append(label);
    fragment.append(field);
  });

  dom.fieldForm.append(fragment);
  dom.entryTabs.hidden = false;
  dom.actions.hidden = false;
}

function setActiveTab(tabName) {
  dom.tabButtons.forEach((button) => {
    const isActive = button.dataset.tab === tabName;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  });

  dom.tabPanels.forEach((panel) => {
    panel.hidden = panel.id !== `${tabName}Panel`;
  });
}

function createTextarea(token) {
  const textarea = document.createElement("textarea");
  textarea.dataset.placeholder = token;
  textarea.name = token;
  textarea.autocomplete = "off";
  textarea.spellcheck = false;
  if (isAutomaticDatePlaceholder(token)) {
    textarea.value = getAutomaticDateReplacements()[token];
    textarea.readOnly = true;
    textarea.title = "Filled automatically with today's date";
  }
  return textarea;
}

function appendDropdownControl(label, token) {
  const select = document.createElement("select");
  select.className = "placeholder-select";
  select.setAttribute("aria-label", `Choose ${humanizePlaceholder(token)}`);

  const emptyOption = document.createElement("option");
  emptyOption.value = "";
  emptyOption.textContent = "Blank / type manually below";
  select.append(emptyOption);

  getDropdownOptions(token).forEach((typeValue) => {
    const option = document.createElement("option");
    option.value = typeValue;
    option.textContent = typeValue;
    select.append(option);
  });

  const textarea = createTextarea(token);
  textarea.placeholder = "Type custom value or choose from dropdown";
  select.addEventListener("change", () => {
    textarea.value = select.value;
  });

  label.append(select, textarea);
}

function humanizePlaceholder(token) {
  const clean = token.replace(/[<>]/g, "").replace(/[_-]+/g, " ").trim();
  return clean
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .replace(/^0i\b/i, "0I");
}

function collectReplacements() {
  const replacements = {};
  dom.fieldForm.querySelectorAll("[data-placeholder]").forEach((field) => {
    replacements[field.dataset.placeholder] = normalizeDateValue(field.value);
  });
  return { ...replacements, ...getAutomaticDateReplacements() };
}

function applyBulkInput() {
  const parsedValues = parseBulkPlaceholderValues(dom.bulkInput.value);
  const entries = Object.entries(parsedValues).filter(([placeholder]) => hasFieldForPlaceholder(placeholder));

  if (!dom.bulkInput.value.trim()) {
    setBulkResult("Paste placeholder values first.", "error");
    return;
  }

  if (!entries.length) {
    setBulkResult("No matching placeholders found for this template.", "error");
    return;
  }

  entries.forEach(([placeholder, value]) => {
    setFieldValue(placeholder, value);
  });

  const ignoredCount = Object.keys(parsedValues).length - entries.length;
  const ignoredText = ignoredCount > 0 ? ` ${ignoredCount} placeholder(s) ignored because they are not in this template.` : "";
  setBulkResult(`Autofilled ${entries.length} field(s).${ignoredText}`, "success");
  setActiveTab("fields");
}

function parseBulkPlaceholderValues(input) {
  const values = {};
  const text = input || "";
  const markerPattern = /<<[^<>]+>>\s*(?:=|\u2192)/g;
  const markers = Array.from(text.matchAll(markerPattern));

  markers.forEach((marker, index) => {
    const placeholderMatch = marker[0].match(/<<[^<>]+>>/);
    if (!placeholderMatch) return;

    const placeholder = placeholderMatch[0];
    const valueStart = marker.index + marker[0].length;
    const valueEnd = index + 1 < markers.length ? markers[index + 1].index : text.length;
    const value = cleanBulkValue(text.slice(valueStart, valueEnd));

    if (value || !(placeholder in values)) {
      values[placeholder] = value;
    }
  });

  return values;
}

function cleanBulkValue(value) {
  const cleaned = value
    .replace(/^\s*[,;|]+\s*/, "")
    .replace(/\s*[,;|]+\s*$/, "")
    .replace(/[ \t]+\n/g, "\n")
    .trim();

  return normalizeDateValue(cleaned);
}

function normalizeDateValue(value) {
  const dateMatch = String(value || "").trim().match(/^(\d{1,2})[-\s]([A-Za-z]{3,9})[-\s](\d{4})$/);
  if (!dateMatch) return value;

  const monthIndex = ENGLISH_MONTH_INDEX[dateMatch[2].toLowerCase()];
  if (monthIndex === undefined) return value;

  const day = dateMatch[1].padStart(2, "0");
  return `${day} de ${SPANISH_MONTHS[monthIndex]} de ${dateMatch[3]}`;
}

function hasFieldForPlaceholder(placeholder) {
  return Boolean(dom.fieldForm.querySelector(`[data-placeholder="${cssEscape(placeholder)}"]`));
}

function setFieldValue(placeholder, value) {
  const field = dom.fieldForm.querySelector(`[data-placeholder="${cssEscape(placeholder)}"]`);
  if (!field || isAutomaticDatePlaceholder(placeholder)) return;

  field.value = value;
  const card = field.closest(".field-card");
  const select = card ? card.querySelector("select") : null;
  if (select) {
    const hasOption = Array.from(select.options).some((option) => option.value === value);
    select.value = hasOption ? value : "";
  }
}

function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") {
    return window.CSS.escape(value);
  }
  return value.replace(/(["\\])/g, "\\$1");
}

function clearBulkInput() {
  dom.bulkInput.value = "";
  setBulkResult("Bulk box cleared.", "success");
}

function setBulkResult(message, type) {
  dom.bulkResult.textContent = message;
  dom.bulkResult.className = `bulk-result ${type || ""}`.trim();
}

function isAutomaticDatePlaceholder(token) {
  return token === "<<T_DATE>>" || token === "<<TODAY_DATE>>";
}

function hasDropdownOptions(token) {
  return getDropdownOptions(token).length > 0;
}

function getDropdownOptions(token) {
  if (token === "<<TYPE>>") {
    return TYPE_OPTIONS;
  }
  if (token === "<<TITLE>>") {
    return TITLE_OPTIONS;
  }
  if (token === "<<RELATION>>") {
    return RELATION_OPTIONS;
  }
  if (token === "<<REGISTRAR>>") {
    return REGISTRAR_OPTIONS;
  }
  return [];
}

function getAutomaticDateReplacements() {
  const today = new Date();
  const day = String(today.getDate()).padStart(2, "0");
  const month = String(today.getMonth() + 1).padStart(2, "0");
  const year = today.getFullYear();

  return {
    "<<T_DATE>>": `${day}/${month}/${year}`,
    "<<TODAY_DATE>>": `${day} de ${SPANISH_MONTHS[today.getMonth()]} de ${year}`,
  };
}

async function buildDocxBlob() {
  if (!state.templateBuffer || !state.selectedKey) {
    throw new Error("Choose a template first.");
  }

  const zip = await JSZip.loadAsync(state.templateBuffer.slice(0));
  const replacements = collectReplacements();
  const fileNames = Object.keys(zip.files).filter((name) => name.startsWith("word/") && name.endsWith(".xml"));

  for (const fileName of fileNames) {
    const file = zip.file(fileName);
    if (!file) continue;

    const xml = await file.async("string");
    zip.file(fileName, replaceXmlTokens(xml, replacements));
  }

  return zip.generateAsync({ type: "blob", mimeType: DOCX_MIME, compression: "DEFLATE" });
}

function replaceXmlTokens(xmlText, replacements) {
  let updated = xmlText;
  const entries = Object.entries(replacements).sort((left, right) => right[0].length - left[0].length);

  for (const [placeholder, value] of entries) {
    const safeValue = toWordTextXml(value || "");
    const escapedPlaceholder = escapeXml(placeholder);
    const variants = new Set([placeholder, escapedPlaceholder]);

    if (placeholder.endsWith(">>")) {
      const malformed = placeholder.slice(0, -1);
      variants.add(malformed);
      variants.add(escapeXml(malformed));
    }

    if (placeholder.startsWith("<<")) {
      const missingOpen = placeholder.slice(1);
      variants.add(missingOpen);
      variants.add(escapeXml(missingOpen));
    }

    variants.forEach((variant) => {
      updated = replaceLiteral(updated, variant, safeValue);
      updated = replaceAllSplitTextTokens(updated, decodeXml(variant), value || "");
    });
  }

  return updated;
}

function replaceLiteral(text, search, replacement) {
  if (!search) return text;
  return text.split(search).join(replacement);
}

function replaceAllSplitTextTokens(xmlText, placeholder, value) {
  let updated = xmlText;

  for (let attempt = 0; attempt < 100; attempt += 1) {
    const next = replaceSplitTextToken(updated, placeholder, value);
    if (next === updated) return updated;
    updated = next;
  }

  return updated;
}

function replaceSplitTextToken(xmlText, placeholder, value) {
  const textNodes = [];
  const joinedParts = [];
  let cursor = 0;

  for (const match of xmlText.matchAll(TEXT_NODE_PATTERN)) {
    const nodeText = decodeXml(match[2]);
    const start = cursor;
    const end = start + nodeText.length;

    textNodes.push({
      contentStart: match.index + match[1].length,
      contentEnd: match.index + match[1].length + match[2].length,
      textStart: start,
      textEnd: end,
      text: nodeText,
    });

    joinedParts.push(nodeText);
    cursor = end;
  }

  const joinedText = joinedParts.join("");
  const tokenStart = joinedText.toLowerCase().indexOf(placeholder.toLowerCase());

  if (tokenStart < 0) {
    return xmlText;
  }

  const tokenEnd = tokenStart + placeholder.length;
  const replacements = [];
  let wroteValue = false;

  textNodes.forEach((node) => {
    if (node.textEnd <= tokenStart || node.textStart >= tokenEnd) {
      return;
    }

    const prefix = tokenStart > node.textStart ? node.text.slice(0, Math.max(tokenStart - node.textStart, 0)) : "";
    const suffix = tokenEnd < node.textEnd ? node.text.slice(tokenEnd - node.textStart) : "";
    const replacementText = wroteValue ? suffix : `${prefix}${value}${suffix}`;
    wroteValue = true;

    replacements.push([node.contentStart, node.contentEnd, toWordTextXml(replacementText)]);
  });

  return replacements.reduceRight((result, [start, end, replacement]) => {
    return result.slice(0, start) + replacement + result.slice(end);
  }, xmlText);
}

function escapeXml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function toWordTextXml(value) {
  return String(value)
    .split(/\r\n|\r|\n/)
    .map((line) => escapeXml(line))
    .join('</w:t><w:br/><w:t xml:space="preserve">');
}

function decodeXml(value) {
  const textarea = decodeXml.textarea || document.createElement("textarea");
  decodeXml.textarea = textarea;
  textarea.innerHTML = value;
  return textarea.value;
}

async function handleDocxDownload() {
  await runGeneration(async () => {
    const blob = await buildDocxBlob();
    state.lastDocxBlob = blob;
    downloadBlob(blob, `${currentOutputName()}.docx`);
    await renderPreview(blob);
    setStatus("MS Word file generated.", "success");
  });
}

async function handlePdfDownload() {
  await runGeneration(async () => {
    if (!window.docx || !window.html2pdf) {
      throw new Error("PDF libraries failed to load. Check internet access for frontend libraries.");
    }

    const blob = await buildDocxBlob();
    state.lastDocxBlob = blob;
    await renderPreview(blob);
    dom.previewBadge.textContent = "Exporting";

    const exportNode = dom.docPreview.querySelector(".docx-wrapper") || dom.docPreview;

    await html2pdf()
      .set({
        filename: `${currentOutputName()}.pdf`,
        margin: 0,
        image: { type: "jpeg", quality: 0.98 },
        html2canvas: { scale: 2, useCORS: true, backgroundColor: "#ffffff" },
        jsPDF: { unit: "pt", format: "a4", orientation: "portrait" },
        pagebreak: { mode: ["css", "legacy"] },
      })
      .from(exportNode)
      .save();

    dom.previewBadge.textContent = "Ready";
    setStatus("PDF file generated.", "success");
  });
}

async function runGeneration(callback) {
  setBusy(true);
  setStatus("Generating document...", "");

  try {
    await callback();
  } catch (error) {
    dom.previewBadge.textContent = "Ready";
    setStatus(error.message || "Document generation failed.", "error");
  } finally {
    setBusy(false);
  }
}

async function renderPreview(blob) {
  if (!window.docx) return;

  dom.previewShell.hidden = false;
  dom.docPreview.replaceChildren();
  dom.previewBadge.textContent = "Rendering";

  await window.docx.renderAsync(blob, dom.docPreview, null, {
    className: "docx",
    inWrapper: true,
    ignoreWidth: false,
    ignoreHeight: false,
    breakPages: true,
    useBase64URL: true,
  });

  dom.previewBadge.textContent = "Ready";
}

function downloadBlob(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function currentOutputName() {
  const template = TEMPLATE_OPTIONS[state.selectedKey];
  const stamp = new Date().toISOString().slice(0, 10);
  return `${template.outputName}-${stamp}`;
}

function clearFields() {
  dom.fieldForm.querySelectorAll("select").forEach((field) => {
    field.selectedIndex = 0;
  });
  dom.fieldForm.querySelectorAll("textarea").forEach((field) => {
    field.value = isAutomaticDatePlaceholder(field.dataset.placeholder)
      ? getAutomaticDateReplacements()[field.dataset.placeholder]
      : "";
  });
  state.lastDocxBlob = null;
  dom.previewShell.hidden = true;
  dom.docPreview.replaceChildren();
  setBulkResult("", "");
  setStatus("Fields cleared.", "success");
}

function setBusy(isBusy) {
  dom.templateSelect.disabled = isBusy;
  dom.downloadDocx.disabled = isBusy;
  dom.downloadPdf.disabled = isBusy;
  dom.resetForm.disabled = isBusy;
  dom.applyBulk.disabled = isBusy;
  dom.clearBulk.disabled = isBusy;
  dom.tabButtons.forEach((field) => {
    field.disabled = isBusy;
  });
  dom.bulkInput.disabled = isBusy;
  dom.fieldForm.querySelectorAll("textarea, select").forEach((field) => {
    field.disabled = isBusy;
  });
}

function setStatus(message, type) {
  dom.status.textContent = message;
  dom.status.className = `status ${type || ""}`.trim();
}

window.manualTemplateApp = {
  extractPlaceholders,
  parseBulkPlaceholderValues,
  replaceXmlTokens,
};