import {language} from './i18n.js';
import {text} from './xray-i18n.js';

const apiRoot = '/api/lung-plugin/xray';
const $ = id => document.getElementById('rx-' + id);
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
  const modelLabel = result?.model ? text('modelUsed') + ' · ' + result.model : '';
  const draftLanguage = result?.requestedLanguage
    ? new Intl.DisplayNames([language()], {type: 'language'}).of(result.requestedLanguage)
    : '';
  $('model-used').textContent = draftLanguage
    ? modelLabel + ' · ' + text('draftLanguage') + ' · ' + draftLanguage
    : modelLabel;
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
    result = {
      text: draft.text,
      model: typeof draft.model === 'string' ? draft.model : '',
      requestedLanguage: typeof draft.requested_language === 'string' ? draft.requested_language : '',
    };
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
