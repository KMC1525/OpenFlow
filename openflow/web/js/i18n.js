// i18n mínimo: a própria frase em português é a chave; `en.js` traduz para inglês.
import EN from './en.js';

let lang = 'pt';
export function setLang(pref) {
  const l = (pref && pref !== 'auto' ? pref : (navigator.language || 'en')).toLowerCase();
  lang = l.startsWith('pt') ? 'pt' : 'en';
  document.documentElement.lang = lang === 'pt' ? 'pt-BR' : 'en';
}
export const getLang = () => lang;
export function t(s, params) {
  let out = lang === 'pt' ? s : (Object.prototype.hasOwnProperty.call(EN, s) ? EN[s] : s);
  if (params) out = out.replace(/\{(\w+)\}/g, (_, k) => (params[k] != null ? params[k] : ''));
  return out;
}
