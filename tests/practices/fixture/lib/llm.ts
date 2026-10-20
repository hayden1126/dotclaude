const API_URL = process.env.LLM_API_URL ?? "https://llm.example.com/v1/complete";
const MODEL = process.env.LLM_MODEL ?? "general-large";

type CompletionResponse = { text: string };

// Sends one prompt to the model provider and returns the reply text.
export async function complete(prompt: string): Promise<string> {
  const res = await fetch(API_URL, {
    method: "POST",
    headers: {
      authorization: `Bearer ${process.env.LLM_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({ model: MODEL, prompt, max_tokens: 512 }),
  });
  if (!res.ok) throw new Error(`LLM request failed with ${res.status}`);
  const data = (await res.json()) as CompletionResponse;
  return data.text;
}
