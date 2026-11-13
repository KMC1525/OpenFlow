// Cliente da API local do OpenFlow.
import { t } from './i18n.js';
export class ApiError extends Error {
  constructor(message, status, data) { super(message); this.status = status; this.data = data; }
}

export async function api(path, { method = 'GET', body, raw, headers } = {}) {
  const opts = { method, headers: Object.assign({}, headers) };
  if (body !== undefined) {
    if (raw) opts.body = body;
    else { opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; }
  }
  let res;
  try { res = await fetch(path, opts); } catch (e) { throw new ApiError(t('Sem conexão com o servidor do OpenFlow.'), 0); }
  const ct = res.headers.get('Content-Type') || '';
  const data = ct.includes('json') ? await res.json().catch(() => ({})) : await res.text();
  if (!res.ok) throw new ApiError((data && data.error) || `Erro ${res.status}`, res.status, data);
  return data;
}

// Server-Sent Events (GET). Devolve função para fechar.
export function events(url, onEvent, onEnd) {
  const es = new EventSource(url);
  es.onmessage = (m) => {
    let ev; try { ev = JSON.parse(m.data); } catch (e) { return; }
    onEvent(ev);
    if (ev.type === 'end') { es.close(); if (onEnd) onEnd(ev); }
  };
  es.onerror = () => { /* o EventSource tenta reconectar sozinho; 'end' encerra */ };
  return () => es.close();
}

// Upload com progresso (corpo cru + X-Filename).
export function upload(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/uploads');
    xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name));
    xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let data = {}; try { data = JSON.parse(xhr.responseText); } catch (e) { /* ok */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data); else reject(new ApiError(data.error || `Erro ${xhr.status}`, xhr.status, data));
    };
    xhr.onerror = () => reject(new ApiError(t('Falha no upload.'), 0));
    xhr.send(file);
  });
}
