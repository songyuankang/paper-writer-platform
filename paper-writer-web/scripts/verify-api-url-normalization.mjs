import assert from "node:assert/strict";
import { buildApiUrl, normalizeApiBase } from "../.api-url-test/apiUrl.js";

const baseCases = [
  ["http://127.0.0.1:8000", "http://127.0.0.1:8000"],
  ["http://127.0.0.1:8000/", "http://127.0.0.1:8000"],
  ["  http://127.0.0.1:8000  ", "http://127.0.0.1:8000"],
  [" http://127.0.0.1:8000 / ", "http://127.0.0.1:8000"],
  [undefined, ""],
];

for (const [input, expected] of baseCases) {
  assert.equal(normalizeApiBase(input), expected);
  assert.equal(
    buildApiUrl(input, "/api/models"),
    `${expected}/api/models`,
  );
  assert.equal(
    buildApiUrl(input, "api/models"),
    `${expected}/api/models`,
  );
}

assert.equal(
  buildApiUrl(" http://127.0.0.1:8000 / ", "/api/models"),
  "http://127.0.0.1:8000/api/models",
);
console.log("API URL normalization tests passed");
