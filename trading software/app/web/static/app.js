async function postJson(url) {
  const resp = await fetch(url, { method: "POST" });
  return resp.json();
}

async function withBusy(btn, label, fn) {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = label;
  try {
    await fn();
  } catch (err) {
    alert("Chyba: " + err);
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

function runPredictions(btn) {
  withBusy(btn, "Běží…", async () => {
    const data = await postJson("/api/run-predictions");
    let msg = `Vytvořeno predikcí: ${data.created}`;
    if (data.models && data.models.length) msg += `\nModely: ${data.models.join(", ")}`;
    if (data.errors && data.errors.length) msg += `\n\nProblémy:\n- ${data.errors.join("\n- ")}`;
    alert(msg);
    location.reload();
  });
}

function runEvaluations(btn) {
  withBusy(btn, "Vyhodnocuji…", async () => {
    const data = await postJson("/api/run-evaluations");
    let msg = `Vyhodnoceno: ${data.evaluated}, přeskočeno: ${data.skipped}`;
    if (data.errors && data.errors.length) msg += `\n\nProblémy:\n- ${data.errors.join("\n- ")}`;
    alert(msg);
    location.reload();
  });
}
