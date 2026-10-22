import { build } from "esbuild";

await build({
  entryPoints: ["src/index.js"],
  bundle: true,
  minify: true,
  format: "iife",
  target: "es2020",
  outfile: "../../webapp/src/static/notebook/vendor/tiptap.bundle.js",
  legalComments: "none",
});
