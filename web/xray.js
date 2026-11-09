import {language} from './i18n.js';

const apiRoot = '/api/lung-plugin/xray';
const $ = id => document.getElementById('rx-' + id);
const strings = {
  accept: ['Li e aceito os termos do modelo.', 'I have read and accept the model terms.'],
  busy: ['O modelo está em uso. Aguarde para gerar outro pré-laudo.', 'The model is busy. Wait before generating another draft.'],
  cancel: ['Cancelar', 'Cancel'],
  checking: ['Verificando modelo local…', 'Checking the local model…'],
  choose: ['Arraste ou escolha um arquivo', 'Drop or choose a file'],
  close: ['Fechar', 'Close'],
  consent: ['Leia e aceite os termos HAI-DEF antes de preparar o modelo.', 'Read and accept the HAI-DEF terms before setting up the model.'],
  copied: ['Rascunho copiado.', 'Draft copied.'],
  copy: ['Copiar rascunho', 'Copy draft'],
  copyFailed: ['Selecione o texto para copiar.', 'Select the text to copy.'],
  dimensions: ['A radiografia tem dimensões incompatíveis. Escolha outra exportação do exame.', 'This X-ray has unsupported dimensions. Choose another export of the exam.'],
  disk: ['Espaço em disco insuficiente. Libere espaço nesta estação e tente novamente.', 'Not enough disk space. Free up space on this workstation and try again.'],
  done: ['Imagem pronta', 'Image ready'],
  download: ['Baixar modelo', 'Download model'],
  downloadFailed: ['Falha ao preparar o modelo. Confira a conexão e tente novamente.', 'Model setup failed. Check the connection and try again.'],
  downloadHelp: ['O preparo baixa cerca de 3,37 GB para processar radiografias frontais de tórax nesta estação.', 'Setup downloads about 3.37 GB to process frontal chest X-rays on this workstation.'],
  downloading: ['Preparando modelo local…', 'Preparing the local model…'],
  draft: ['RASCUNHO NÃO VERIFICADO', 'UNVERIFIED DRAFT'],
  dropHint: ['Arraste um arquivo ou escolha no computador', 'Drop a file or choose one from your computer'],
  emptyFile: ['O arquivo selecionado está vazio.', 'The selected file is empty.'],
  fileTooLarge: ['O arquivo excede o tamanho aceito.', 'The file exceeds the allowed size.'],
  formats: ['DICOM DX/CR, JPEG ou PNG', 'DICOM DX/CR, JPEG or PNG'],
  generate: ['Gerar pré-laudo', 'Generate draft'],
  generating: ['Gerando o pré-laudo nesta estação…', 'Generating a draft on this workstation…'],
  imageTitle: ['Radiografia frontal de tórax', 'Frontal chest X-ray'],
  invalidImage: ['Não foi possível abrir a radiografia. Escolha um DICOM DX/CR, JPEG ou PNG válido.', 'Could not open the X-ray. Choose a valid DICOM DX/CR, JPEG or PNG file.'],
  license: ['Termos do Google HAI-DEF', 'Google HAI-DEF terms'],
  localUpload: ['A imagem é processada neste computador.', 'The image is processed on this computer.'],
  memory: ['Memória insuficiente para executar o modelo. Feche outros aplicativos e tente novamente.', 'Not enough memory to run the model. Close other applications and try again.'],
  modelMissing: ['Prepare o modelo de radiografia para gerar pré-laudos.', 'Set up the X-ray model to generate drafts.'],
  modelProgress: ['Download do modelo', 'Model download'],
  modelReady: ['Modelo disponível nesta estação.', 'Model available on this workstation.'],
  modelUsed: ['Modelo usado', 'Model used'],
  multiple: ['Escolha uma radiografia por vez.', 'Choose one X-ray at a time.'],
  openUpload: ['Adicionar radiografia', 'Add X-ray'],
  platform: ['O modelo de radiografia requer uma estação Windows de 64 bits compatível.', 'The X-ray model requires a compatible 64-bit Windows workstation.'],
  prepare: ['Preparar modelo', 'Set up model'],
  previewAlt: ['Prévia da radiografia selecionada', 'Preview of the selected X-ray'],
  replace: ['Trocar imagem', 'Replace image'],
  reportEmpty: ['Adicione uma radiografia para iniciar.', 'Add an X-ray to get started.'],
  reportError: ['Não foi possível gerar um rascunho. Tente novamente.', 'Could not generate a draft. Try again.'],
  reportProgress: ['Geração do rascunho', 'Draft generation'],
  reportReady: ['Imagem pronta para gerar um pré-laudo.', 'Image ready for draft generation.'],
  reportReview: ['Rascunho gerado. Revisão médica pendente.', 'Draft generated. Medical review pending.'],
  reportTitle: ['Laudo sintético', 'Synthetic report'],
  subtitle: ['Radiografia de tórax · processamento local', 'Chest X-ray · local processing'],
  resources: ['Os arquivos do modelo não passaram na verificação. Prepare o modelo novamente.', 'The model files did not pass verification. Set up the model again.'],
  statusError: ['Não foi possível consultar o modelo local.', 'Could not check the local model.'],
  title: ['Laudo sintético · Raios X', 'Synthetic report · X-ray'],
  timeout: ['A geração atingiu o limite de tempo. Feche outros aplicativos e tente novamente.', 'Draft generation reached its time limit. Close other applications and try again.'],
  unsupported: ['O exame não é compatível com esta tela. Use uma radiografia frontal de tórax DICOM DX/CR, JPEG ou PNG.', 'This exam is unsupported on this page. Use a frontal chest X-ray in DICOM DX/CR, JPEG or PNG format.'],
  uploadProgress: ['Carregamento local', 'Local upload'],
  uploadTitle: ['Carregar radiografia', 'Load X-ray'],
  uploading: ['Lendo arquivo nesta estação…', 'Reading the file on this workstation…'],
  use: ['Usar imagem', 'Use image'],
  validating: ['Preparando prévia…', 'Preparing preview…'],
  warning: ['Pré-laudo experimental. Revise a imagem e o texto antes de qualquer uso clínico.', 'Experimental draft. Review the image and text before any clinical use.'],
};

const text = key => strings[key][language() === 'pt-BR' ? 0 : 1];
const errorKeys = {
  insufficient_disk: 'disk',
  insufficient_memory: 'memory',
  unsupported_platform: 'platform',
  image_dimensions_invalid: 'dimensions',
  resources_invalid: 'resources',
  report_timeout: 'timeout',
  consent_required: 'consent',
  xray_busy: 'busy',
  model_not_prepared: 'modelMissing',
  download_failed: 'downloadFailed',
  unsupported_xray: 'unsupported',
};
const errorKey = (code, fallback) => Object.hasOwn(errorKeys, code) ? errorKeys[code] : fallback;
let model = null;
let statusEpoch = 0;
let modelRequest = false;
let connectionFailed = false;
let preview = null;
let candidate = null;
let upload = null;
let transfer = null;
let result = null;
let generating = false;
let reportError = null;
let uploadError = null;
let copyStatus = null;

function updateText() {
  for (const element of document.querySelectorAll('[data-rx-text]')) {
    if (element.id !== 'rx-model-state' && element.id !== 'rx-report-state') {
      element.textContent = text(element.dataset.rxText);
    }
  }
  for (const element of document.querySelectorAll('[data-rx-label]')) {
    element.setAttribute(element.tagName === 'IMG' ? 'alt' : 'aria-label', text(element.dataset.rxLabel));
  }
  document.title = text('title');
  const heading = document.querySelector('.rx-shell .ui-fn-tag > span[data-radai-frase]');
  const subtitle = document.querySelector('.rx-shell .ui-fn-frase');
  if (heading) heading.textContent = text('title');
  if (subtitle) subtitle.textContent = text('subtitle');
  render();
}

function progress(element, visible, value, maximum = 1) {
  element.hidden = !visible;
  element.max = maximum;
  if (Number.isFinite(value)) {
    element.value = Math.max(0, Math.min(value, maximum));
  } else {
    element.removeAttribute('value');
  }
}

function reportState() {
  if (copyStatus) return copyStatus;
  if (generating) return 'generating';
  if (result) return 'reportReview';
  return preview ? 'reportReady' : 'reportEmpty';
}

function modelState() {
  if (modelRequest || model?.preparing) return 'downloading';
  if (connectionFailed) return 'statusError';
  if (!model) return 'checking';
  if (model.running) return 'busy';
  if (model.ready) return 'modelReady';
  return model.error ? errorKey(model.error, 'downloadFailed') : 'modelMissing';
}

function render() {
  const preparing = modelRequest || Boolean(model?.preparing);
  const busy = generating || Boolean(model?.running);
  $('model-state').textContent = text(modelState());
  const total = Number(model?.total_bytes) || 0;
  const received = Number(model?.downloaded_bytes) || 0;
  if (preparing && total > 0) {
    const mb = new Intl.NumberFormat(language(), {maximumFractionDigits: 1});
    $('model-state').textContent += ' ' + mb.format(received / 1e6) + ' / ' + mb.format(total / 1e6) + ' MB';
  }
  progress($('model-progress'), preparing, total > 0 ? received : null, total || 1);
  $('prepare').hidden = Boolean(model?.ready);
  $('prepare').disabled = !model || preparing || busy;
  $('open-upload').hidden = Boolean(preview);
  $('replace').hidden = !preview;
  $('open-upload').disabled = generating;
  $('replace').disabled = generating;
  $('image').hidden = !preview;
  if (preview && $('image').src !== preview.url) $('image').src = preview.url;
  $('generate').disabled = !preview || !model?.ready || busy || preparing;
  $('copy').hidden = !result;
  $('copy').disabled = !result || busy;
  $('report-state').textContent = text(reportState());
  $('result').hidden = !result;
  if ($('result').textContent !== (result?.text ?? '')) $('result').textContent = result?.text ?? '';
  $('model-used').hidden = !result?.model;
  $('model-used').textContent = result?.model ? text('modelUsed') + ' · ' + result.model : '';
  progress($('report-progress'), generating);
  $('error').hidden = !reportError;
  $('error').textContent = reportError ? text(reportError) : '';
  $('choose').hidden = Boolean(transfer);
  $('transfer').hidden = !transfer;
  $('transfer-check').hidden = transfer?.stage !== 'done';
  $('filename').textContent = transfer?.name ?? '';
  $('transfer-state').textContent = transfer ? text(transfer.stage) : '';
  progress($('transfer-progress'), Boolean(transfer && transfer.stage !== 'done'), transfer?.fraction);
  $('use').disabled = !candidate;
  $('upload-error').hidden = !uploadError;
  $('upload-error').textContent = uploadError ? text(uploadError) : '';
}

async function jsonRequest(path, options) {
  const response = await fetch(apiRoot + path, {cache: 'no-store', ...options});
  const value = await response.json().catch(() => null);
  if (!response.ok || !value) {
    throw new Error(value?.error ?? ('http_' + response.status));
  }
  return value;
}

async function refreshModel() {
  const epoch = ++statusEpoch;
  try {
    const status = await jsonRequest('/status');
    if (epoch !== statusEpoch) return;
    model = status;
    connectionFailed = false;
  } catch {
    if (epoch !== statusEpoch) return;
    connectionFailed = true;
    model = null;
  }
  render();
}

async function pollModel() {
  await refreshModel();
  window.setTimeout(pollModel, modelRequest || model?.preparing || model?.running ? 1200 : 5000);
}

function openUpload() {
  if (!generating && !$('upload').open) {
    $('upload').showModal();
  }
}

function resetCandidate() {
  const current = upload;
  upload = null;
  current?.abort();
  if (candidate) URL.revokeObjectURL(candidate.url);
  candidate = null;
  transfer = null;
  uploadError = null;
  $('file').value = '';
  render();
}

function addFiles(fileList) {
  const files = Array.from(fileList);
  if (generating || !files.length) return;
  openUpload();
  resetCandidate();
  if (files.length !== 1) {
    uploadError = 'multiple';
    render();
    return;
  }
  const file = files[0];
  if (!file.size) {
    uploadError = 'emptyFile';
    render();
    return;
  }
  const request = new XMLHttpRequest();
  upload = request;
  transfer = {name: file.name, stage: 'uploading', fraction: 0};
  render();
  request.open('POST', apiRoot + '/preview');
  request.responseType = 'blob';
  request.timeout = 60000;
  request.setRequestHeader('Content-Type', 'application/octet-stream');
  const fail = (key = 'invalidImage') => {
    if (upload !== request) return;
    resetCandidate();
    uploadError = key;
    render();
  };
  request.upload.onprogress = event => {
    if (upload !== request || !event.lengthComputable) return;
    transfer.fraction = event.loaded / event.total;
    render();
  };
  request.upload.onload = () => {
    if (upload !== request) return;
    transfer.stage = 'validating';
    transfer.fraction = null;
    render();
  };
  request.onerror = () => fail();
  request.ontimeout = () => fail();
  request.onload = async () => {
    if (upload !== request) return;
    const png = request.response;
    if (request.status !== 200 || !png?.size || png.type.split(';')[0] !== 'image/png') {
      const problem = await png?.text().then(JSON.parse).catch(() => null);
      fail(request.status === 413 ? 'fileTooLarge' : errorKey(problem?.error, 'invalidImage'));
      return;
    }
    const url = URL.createObjectURL(png);
    const image = new Image();
    image.src = url;
    try {
      await image.decode();
    } catch {
      URL.revokeObjectURL(url);
      fail();
      return;
    }
    if (upload !== request) {
      URL.revokeObjectURL(url);
      return;
    }
    upload = null;
    candidate = {url, png};
    transfer.stage = 'done';
    render();
    $('use').focus();
  };
  request.send(file);
}

function dropZone(element) {
  element.addEventListener('dragover', event => {
    if (!Array.from(event.dataTransfer?.types ?? []).includes('Files')) return;
    event.preventDefault();
    element.dataset.drag = 'true';
  });
  element.addEventListener('dragleave', event => {
    if (!element.contains(event.relatedTarget)) delete element.dataset.drag;
  });
  element.addEventListener('drop', event => {
    event.preventDefault();
    delete element.dataset.drag;
    if (event.dataTransfer?.files) addFiles(event.dataTransfer.files);
  });
}

$('open-upload').addEventListener('click', openUpload);
$('replace').addEventListener('click', openUpload);
$('choose').addEventListener('click', () => $('file').click());
$('file').addEventListener('change', event => addFiles(event.target.files));
$('upload').addEventListener('close', () => {
  if (!$('upload').open) resetCandidate();
});
dropZone($('viewer'));
dropZone($('upload'));

$('use').addEventListener('click', () => {
  if (!candidate) return;
  if (preview) URL.revokeObjectURL(preview.url);
  preview = candidate;
  candidate = null;
  result = null;
  reportError = null;
  copyStatus = null;
  $('upload').close();
  render();
  $('replace').focus();
});

for (const button of document.querySelectorAll('[data-rx-close]')) {
  button.addEventListener('click', () => $(button.dataset.rxClose).close());
}

$('prepare').addEventListener('click', () => {
  $('accept').checked = false;
  $('download').disabled = true;
  $('license').showModal();
});
$('accept').addEventListener('change', () => {
  $('download').disabled = !$('accept').checked;
});
$('download').addEventListener('click', async () => {
  if (!$('accept').checked || modelRequest) return;
  $('license').close();
  modelRequest = true;
  reportError = null;
  render();
  try {
    await jsonRequest('/prepare', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({accept: true}),
    });
  } catch (error) {
    reportError = errorKey(error.message, 'downloadFailed');
  } finally {
    modelRequest = false;
    await refreshModel();
  }
});

$('generate').addEventListener('click', async () => {
  if ($('generate').disabled || !preview || generating) return;
  generating = true;
  reportError = null;
  result = null;
  copyStatus = null;
  render();
  try {
    const draft = await jsonRequest('/report', {
      method: 'POST',
      headers: {'Content-Type': 'image/png', 'Accept-Language': language()},
      body: preview.png,
    });
    if (typeof draft.text !== 'string' || !draft.text.trim()) throw new Error('empty_result');
    result = {text: draft.text, model: typeof draft.model === 'string' ? draft.model : ''};
  } catch (error) {
    reportError = errorKey(error.message, error.message === 'http_409' ? 'busy' : 'reportError');
  } finally {
    generating = false;
    await refreshModel();
  }
});

$('copy').addEventListener('click', async () => {
  if (!result) return;
  try {
    await navigator.clipboard.writeText(text('draft') + '\n\n' + result.text);
    copyStatus = 'copied';
  } catch {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents($('result'));
    selection?.removeAllRanges();
    selection?.addRange(range);
    copyStatus = 'copyFailed';
  }
  render();
});

window.addEventListener('pagehide', event => {
  if (event.persisted) return;
  resetCandidate();
  if (preview) URL.revokeObjectURL(preview.url);
});
updateText();
new MutationObserver(updateText).observe(document.documentElement, {attributes: true, attributeFilter: ['lang']});
pollModel();
