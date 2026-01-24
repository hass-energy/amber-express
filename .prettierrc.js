/** @type {import("prettier").Config} */
module.exports = {
  arrowParens: "always",
  bracketSpacing: true,
  endOfLine: "lf",
  jsonRecursiveSort: true,
  plugins: ["prettier-plugin-sort-json"],
  printWidth: 120,
  proseWrap: "preserve",
  quoteProps: "as-needed",
  semi: true,
  singleQuote: false,
  tabWidth: 2,
  trailingComma: "es5",
  useTabs: false,
  overrides: [
    {
      // Home Assistant manifest.json - domain and name first, then alphabetical
      files: "custom_components/amber_express/manifest.json",
      options: {
        jsonSortOrder: JSON.stringify({
          domain: null,
          name: null,
          "/.*/": "lexical",
        }),
      },
    },
    {
      // HACS json files
      files: "hacs.json",
      options: {
        jsonSortOrder: JSON.stringify({
          name: null,
          hacs: null,
          homeassistant: null,
          "/.*/": "lexical",
        }),
      },
    },
    {
      // Home Assistant translation files - semantic ordering for config flows
      files: "custom_components/amber_express/translations/*.json",
      options: {
        objectWrap: "collapse",
        jsonSortOrder: JSON.stringify({
          // Flow-level keys
          config: null,
          options: null,
          flow_title: null,
          step: null,
          error: null,
          abort: null,

          // Step content keys
          title: null,
          description: null,
          data: null,
          data_description: null,

          // Entity keys
          entity: null,
          sensor: null,
          binary_sensor: null,
          name: null,

          // Everything else sorted lexically
          "/.*/": "lexical",
        }),
      },
    },
  ],
};
