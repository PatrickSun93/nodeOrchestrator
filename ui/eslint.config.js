import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
    },
  },
  // binds-API-only rule: fetch/WebSocket only allowed in src/api/
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/api/**"],
    rules: {
      "no-restricted-globals": [
        "error",
        {
          name: "fetch",
          message:
            "Use the typed client in src/api/client.ts — fetch is forbidden outside src/api/ (HR#2 binds-API-only).",
        },
        {
          name: "WebSocket",
          message:
            "Use the typed stream client in src/api/stream.ts — WebSocket is forbidden outside src/api/ (HR#2 binds-API-only).",
        },
      ],
    },
  },
);
