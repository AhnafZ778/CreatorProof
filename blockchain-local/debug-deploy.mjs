import fs from "fs";
import solc from "solc";
import { ethers } from "ethers";

const source = fs.readFileSync("contracts/CreatorProofEAS.sol", "utf8");
const input = {
  language: "Solidity",
  sources: { "CreatorProofEAS.sol": { content: source } },
  settings: {
    optimizer: { enabled: true, runs: 200 },
    outputSelection: { "*": { "*": ["abi", "evm.bytecode"] } },
  },
};
const out = JSON.parse(solc.compile(JSON.stringify(input)));
const contracts = out.contracts["CreatorProofEAS.sol"];
const provider = new ethers.JsonRpcProvider("http://127.0.0.1:8545");
const wallet = new ethers.Wallet(
  "0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d",
  provider,
);

console.log("nonce before", await provider.getTransactionCount(wallet.address));
const Registry = new ethers.ContractFactory(
  contracts.SchemaRegistry.abi,
  "0x" + contracts.SchemaRegistry.evm.bytecode.object.replace(/^0x/, ""),
  wallet,
);
const registryTx = await Registry.getDeployTransaction();
console.log("registry data len", registryTx.data.length);

const registry = await Registry.deploy();
const rTx = registry.deploymentTransaction();
console.log("registry deploy hash", rTx?.hash, "nonce", rTx?.nonce);
await registry.waitForDeployment();
const registryAddress = await registry.getAddress();
console.log("registry address", registryAddress);
console.log("nonce after registry", await provider.getTransactionCount(wallet.address));

const EAS = new ethers.ContractFactory(
  contracts.EAS.abi,
  "0x" + contracts.EAS.evm.bytecode.object.replace(/^0x/, ""),
  wallet,
);
const eas = await EAS.deploy(registryAddress);
const eTx = eas.deploymentTransaction();
console.log("eas deploy hash", eTx?.hash, "nonce", eTx?.nonce);
await eas.waitForDeployment();
const easAddress = await eas.getAddress();
console.log("eas address", easAddress);
console.log("same?", easAddress === registryAddress);
console.log("reg code", (await provider.getCode(registryAddress)).length);
console.log("eas code", (await provider.getCode(easAddress)).length);
