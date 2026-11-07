const PROVIDER_URL = process.env.PAYMENTS_API_URL ?? "https://payments.example.com/v1/charges";

export type Charge = { id: string; amount_cents: number };

// Charges a card through the provider. Throws when the provider declines it or can't be reached.
export async function chargeCard(cardToken: string, amountCents: number): Promise<Charge> {
  const response = await fetch(PROVIDER_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.PAYMENTS_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ source: cardToken, amount: amountCents, currency: "eur" }),
  });
  if (!response.ok) throw new Error(`The charge failed with ${response.status}`);
  const { id } = await response.json();
  return { id, amount_cents: amountCents };
}
