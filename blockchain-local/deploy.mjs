#!/usr/bin/env node
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import solc from "solc";
import { ethers } from "ethers";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const RPC = process.env.LOCAL_EVM_RPC || "http://127.0.0.1:8545";
const ARTIFACT = path.join(__dirname, "deployment.json");
const PRIVATE_KEY =
  process.env.GANACHE_PRIVATE_KEY ||
  "0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d";

const SOURCE_FILES = ["CreatorProofEAS.sol", "CreatorProofNetwork.sol"];

function compile() {
  const sources = {};
  for (const file of SOURCE_FILES) {
    sources[file] = { content: fs.readFileSync(path.join(__dirname, "contracts", file), "utf8") };
  }
  const input = {
    language: "Solidity",
    sources,
    settings: {
      optimizer: { enabled: true, runs: 200 },
      outputSelection: { "*": { "*": ["abi", "evm.bytecode"] } },
    },
  };
  const output = JSON.parse(solc.compile(JSON.stringify(input)));
  const fatal = (output.errors || []).filter((e) => e.severity === "error");
  if (fatal.length) {
    console.error(fatal.map((e) => e.formattedMessage).join("\n"));
    process.exit(1);
  }
  return output.contracts;
}

function bytecode(contract) {
  const raw = contract.evm.bytecode.object || "";
  if (!raw) throw new Error("missing bytecode");
  return raw.startsWith("0x") ? raw : `0x${raw}`;
}

async function main() {
  const compiled = compile();
  const contracts = compiled["CreatorProofEAS.sol"];
  const network = compiled["CreatorProofNetwork.sol"];
  const provider = new ethers.JsonRpcProvider(RPC);
  const wallet = new ethers.Wallet(PRIVATE_KEY, provider);
  const attester = await wallet.getAddress();
  let nonce = await provider.getTransactionCount(attester, "pending");

  const Registry = new ethers.ContractFactory(
    contracts.SchemaRegistry.abi,
    bytecode(contracts.SchemaRegistry),
    wallet,
  );
  const registry = await Registry.deploy({ nonce: nonce++ });
  await registry.waitForDeployment();
  const registryAddress = await registry.getAddress();

  const EASFactory = new ethers.ContractFactory(
    contracts.EAS.abi,
    bytecode(contracts.EAS),
    wallet,
  );
  const eas = await EASFactory.deploy(registryAddress, { nonce: nonce++ });
  await eas.waitForDeployment();
  const easAddress = await eas.getAddress();

  if (easAddress.toLowerCase() === registryAddress.toLowerCase()) {
    throw new Error(`EAS and registry resolved to the same address: ${easAddress}`);
  }
  if ((await provider.getCode(easAddress)) === "0x") {
    throw new Error("EAS bytecode missing at deployed address");
  }

  const iface = new ethers.Interface(contracts.SchemaRegistry.abi);
  async function registerSchema(schema, revocable) {
    const tx = await registry.register(schema, ethers.ZeroAddress, revocable, {
      nonce: nonce++,
    });
    const receipt = await tx.wait();
    for (const log of receipt.logs) {
      try {
        const parsed = iface.parseLog(log);
        if (parsed?.name === "Registered") return parsed.args.uid;
      } catch {
        // ignore
      }
    }
    throw new Error(`Registered event missing for ${schema}`);
  }

  const packetUid = await registerSchema("bytes32 packetHash", true);
  const checkpointUid = await registerSchema("bytes32 checkpointHash", false);
  // A counterparty may withdraw its commitment, so this schema stays revocable.
  const coAttestationUid = await registerSchema("bytes32 coAttestationHash", true);
  const codeSha = ethers.sha256(await provider.getCode(easAddress)).replace(/^0x/, "");

  // Membership governance and the soulbound clearance receipt. The deploying key
  // is the initial governor and issuer; on a shared deployment governance should be
  // transferred to a separate account immediately after provisioning.
  const MemberRegistry = new ethers.ContractFactory(
    network.CreatorProofMemberRegistry.abi,
    bytecode(network.CreatorProofMemberRegistry),
    wallet,
  );
  const memberRegistry = await MemberRegistry.deploy(attester, { nonce: nonce++ });
  await memberRegistry.waitForDeployment();
  const memberRegistryAddress = await memberRegistry.getAddress();

  const ClearanceReceipt = new ethers.ContractFactory(
    network.CreatorProofClearanceReceipt.abi,
    bytecode(network.CreatorProofClearanceReceipt),
    wallet,
  );
  const clearanceReceipt = await ClearanceReceipt.deploy(memberRegistryAddress, attester, {
    nonce: nonce++,
  });
  await clearanceReceipt.waitForDeployment();
  const clearanceReceiptAddress = await clearanceReceipt.getAddress();

  const platformOrgId = ethers.id("creatorproof.platform");
  const ROLE_PLATFORM = 1;
  await (
    await memberRegistry.enroll(attester, platformOrgId, ROLE_PLATFORM, { nonce: nonce++ })
  ).wait();

  const deployment = {
    rpc: RPC,
    chainId: Number((await provider.getNetwork()).chainId),
    attester,
    privateKey: PRIVATE_KEY,
    eas: easAddress,
    registry: registryAddress,
    packetSchemaUid: packetUid,
    checkpointSchemaUid: checkpointUid,
    coAttestationSchemaUid: coAttestationUid,
    memberRegistry: memberRegistryAddress,
    clearanceReceipt: clearanceReceiptAddress,
    platformOrgId,
    easCodeSha256: codeSha,
  };
  fs.writeFileSync(ARTIFACT, JSON.stringify(deployment, null, 2));
  console.log(JSON.stringify(deployment, null, 2));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
