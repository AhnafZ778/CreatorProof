#!/usr/bin/env node
/**
 * Start a deterministic local EVM for CreatorProof blockchain demos.
 * Account 0 private key is fixed so API .env can pin the attester.
 */
import ganache from "ganache";

const HOST = process.env.LOCAL_EVM_HOST || "127.0.0.1";
const PORT = Number(process.env.LOCAL_EVM_PORT || 8545);
const CHAIN_ID = Number(process.env.LOCAL_EVM_CHAIN_ID || 31337);

// Fixed key used by deploy.mjs / CreatorProof local profile.
const PRIVATE_KEY = "4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d";

const server = ganache.server({
  chain: { chainId: CHAIN_ID },
  wallet: {
    richAccounts: true,
    totalAccounts: 5,
    accounts: [
      {
        secretKey: `0x${PRIVATE_KEY}`,
        balance: 100n * 10n ** 18n,
      },
    ],
  },
  logging: { quiet: true },
});

server.listen(PORT, HOST, (err) => {
  if (err) {
    console.error(err);
    process.exit(1);
  }
  console.log(
    JSON.stringify({
      status: "listening",
      rpc: `http://${HOST}:${PORT}`,
      chainId: CHAIN_ID,
      attesterPrivateKey: `0x${PRIVATE_KEY}`,
    }),
  );
});
