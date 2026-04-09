import { wrapFetchWithPayment } from "@x402/fetch";
import { x402Client, x402HTTPClient } from "@x402/core/client";
import { registerExactEvmScheme } from "@x402/evm/exact/client";
import { privateKeyToAccount } from "viem/accounts";

const args = new Set(process.argv.slice(2));
const challengeOnly = args.has("--challenge-only");
const baseUrl = (process.env.DAEDALMAP_API_BASE_URL || "https://app.daedalmap.com").replace(/\/$/, "");
const endpoint = `${baseUrl}/api/v1/query/dataset`;

const payload = {
  request_id: `buyer-test-${Date.now()}`,
  source_id: "earthquakes_events",
  metrics: ["magnitude"],
  filters: {
    time: {
      start: "2024-01-01",
      end: "2024-12-31",
    },
    region_ids: ["usa"],
  },
  limit: 5,
  output: {
    format: "rows",
  },
};

function decodePaymentRequired(headerValue) {
  if (!headerValue) {
    return null;
  }
  try {
    const decoded = Buffer.from(headerValue, "base64").toString("utf8");
    return JSON.parse(decoded);
  } catch (error) {
    return {
      decode_error: String(error),
      raw: headerValue,
    };
  }
}

async function readBody(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function runChallengeProbe() {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const paymentRequired = response.headers.get("payment-required");
  const decodedRequirements = decodePaymentRequired(paymentRequired);
  const body = await readBody(response);

  console.log("Challenge probe:");
  console.log(JSON.stringify({
    status: response.status,
    payment_required_present: Boolean(paymentRequired),
    payment_requirements: decodedRequirements,
    body,
  }, null, 2));

  return response;
}

async function runPaidRequest() {
  const rawPrivateKey = (process.env.EVM_PRIVATE_KEY || "").trim();
  const privateKey = rawPrivateKey.startsWith("0x") ? rawPrivateKey : `0x${rawPrivateKey}`;
  if (!privateKey) {
    throw new Error("EVM_PRIVATE_KEY is required for paid x402 retries.");
  }

  const signer = privateKeyToAccount(privateKey);
  const client = new x402Client();
  registerExactEvmScheme(client, { signer });
  const fetchWithPayment = wrapFetchWithPayment(fetch, client);

  const response = await fetchWithPayment(endpoint, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const body = await readBody(response);
  const httpClient = new x402HTTPClient(client);
  let settleResponse = null;
  let settleResponseError = null;
  try {
    settleResponse = httpClient.getPaymentSettleResponse(
      (name) => response.headers.get(name),
    );
  } catch (error) {
    settleResponseError = String(error);
  }

  console.log("Paid request:");
  console.log(JSON.stringify({
    status: response.status,
    settle_response_error: settleResponseError,
    settle_response: settleResponse,
    body,
  }, null, 2));
}

async function main() {
  console.log(`Testing x402 endpoint: ${endpoint}`);
  console.log(`Mode: ${challengeOnly ? "challenge-only" : "challenge + paid retry"}`);
  await runChallengeProbe();

  if (challengeOnly) {
    return;
  }

  await runPaidRequest();
}

main().catch((error) => {
  console.error("x402 dataset test failed:");
  console.error(error);
  process.exitCode = 1;
});
