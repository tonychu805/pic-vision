// One rule, and it is the point: no-undef.
//
// Two releases in three days shipped a crash that was a reference to a
// variable that did not exist:
//
//   1.5.0  `span is not defined`       -- ADR-105. A refactor deleted the
//          variable and left one use of it three lines below. The app
//          died on launch.
//   1.5.3  `cancelling is not defined` -- a scripted edit put a useState
//          in the wrong component (it matched the file's FIRST `starting`
//          state, in LiveViewButton, while the code using it was in
//          CloudJobRow). The interface vanished on Retry.
//
// Neither is subtle, and neither is catchable by the tools that were
// running. A bundler resolves a free identifier to "some global, decided
// at runtime" and says nothing. The test suite only fails on code it
// executes, and neither line was executed by a test. Both would have been
// caught here, before either build was cut.
//
// Deliberately minimal. This is not a style pass -- no formatting rules,
// no opinions about hooks or imports, nothing that would produce a wall
// of findings on existing code and train everyone to ignore the output.
// It catches the class of bug that has actually reached operators twice,
// and it is wired into `npm test` so it cannot be forgotten.
import globals from "globals";

export default [
  {
    // Renderer: browser globals, JSX, ES modules.
    files: ["src/**/*.js", "src/**/*.jsx"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "module",
      globals: { ...globals.browser },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    linterOptions: { reportUnusedDisableDirectives: true },
    rules: {
      "no-undef": "error",
      // The other half of the same mistake: a variable declared and then
      // never used is what `cancelling` looked like in LiveViewButton,
      // where the scripted edit actually landed it. Warn rather than
      // error -- it is a smell, not always a defect -- but say it.
      "no-unused-vars": ["warn", { args: "none", varsIgnorePattern: "^_" }],
    },
  },
  {
    // Main process: Node globals, ES modules.
    files: ["electron/**/*.js"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "module",
      globals: { ...globals.node },
    },
    rules: {
      "no-undef": "error",
      "no-unused-vars": ["warn", { args: "none", varsIgnorePattern: "^_" }],
    },
  },
  {
    // preload is CommonJS by necessity (Electron resolves a preload's
    // module type by extension, not by package.json "type").
    files: ["electron/**/*.cjs"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "commonjs",
      globals: { ...globals.node },
    },
    rules: { "no-undef": "error" },
  },
];
