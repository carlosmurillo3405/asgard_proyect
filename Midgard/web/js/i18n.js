// Idiomas de Midgard Web: los textos se escriben en inglés y se traducen con los
// mismos catálogos de la aplicación de escritorio (locale/common.es.json y
// locale/midgard.es.json) más locale/web.es.json, con lo que solo usa la web.

export const LANGUAGES = ["en", "es"];
export const LANGUAGE_NAMES = { en: "English", es: "Español" };
const CATALOGS = ["common", "midgard", "web"];

let current = "en";
let catalog = {};

export function systemLanguage() {
  for (const code of navigator.languages || [navigator.language]) {
    const short = String(code || "").slice(0, 2).toLowerCase();
    if (LANGUAGES.includes(short)) return short;
  }
  return "en";
}

export function resolve(setting) {
  return LANGUAGES.includes(setting) ? setting : systemLanguage();
}

/** Picks the language («auto», «en» or «es») and loads its catalogs. */
export async function setLanguage(setting) {
  const language = resolve(setting);
  const loaded = {};
  if (language !== "en") {
    await Promise.all(CATALOGS.map(async (name) => {
      try {
        const response = await fetch(`locale/${name}.${language}.json`, { cache: "no-cache" });
        if (response.ok) Object.assign(loaded, await response.json());
      } catch {
        // sin catálogo se muestra el texto en inglés
      }
    }));
  }
  catalog = loaded;
  current = language;
  document.documentElement.lang = language;
  return language;
}

export function language() {
  return current;
}

/** Text in the current language; ``{name}`` is replaced with values[name] (like Python's str.format). */
export function tr(text, values) {
  let result = Object.prototype.hasOwnProperty.call(catalog, text) ? catalog[text] : text;
  if (values) {
    result = result.replace(/\{(\w+)\}/g, (match, key) => (key in values ? String(values[key]) : match));
  }
  return result;
}
