import fs from "fs";
import solc from "solc";

const source = fs.readFileSync("contracts/CreatorProofEAS.sol", "utf8");
const input = {
  language: "Solidity",
  sources: { "CreatorProofEAS.sol": { content: source } },
  settings: { outputSelection: { "*": { "*": ["evm.bytecode"] } } },
};
const out = JSON.parse(solc.compile(JSON.stringify(input)));
if (out.errors) console.log(out.errors.map((e) => e.severity + ": " + e.message).join("\n"));
for (const [name, c] of Object.entries(out.contracts["CreatorProofEAS.sol"] || {})) {
  console.log(name, "bytecode_len", (c.evm.bytecode.object || "").length);
}
