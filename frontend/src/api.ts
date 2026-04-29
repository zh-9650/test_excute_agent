const BASE = "http://localhost:8765/api/v1";

export async function uploadCases(file: File) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/cases/upload`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getCases(suiteId: string) {
  const res = await fetch(`${BASE}/cases/${suiteId}`);
  return res.json();
}

export async function getHealth() {
  const res = await fetch(`${BASE}/health`);
  return res.json();
}

export async function getConfig() {
  const res = await fetch(`${BASE}/config`);
  return res.json();
}

export async function getHealing() {
  const res = await fetch(`${BASE}/healing`);
  return res.json();
}

export async function clearHealing() {
  const res = await fetch(`${BASE}/healing/clear`, { method: "POST" });
  return res.json();
}
