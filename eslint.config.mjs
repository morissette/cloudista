import js from "@eslint/js";
import globals from "globals";
export default [
  js.configs.recommended,
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        turnstile: "readonly",
      },
    },
    rules: {
      "no-unused-vars": "warn",
    },
  },
];
