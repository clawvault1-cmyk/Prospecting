function wordCount(text) {
  const found = (text || "").match(/[A-Za-z0-9]+(?:['’-]?[A-Za-z0-9]+)*/g);
  return found ? found.length : 0;
}

function setupSelection() {
  const form = document.getElementById("process-form");
  if (!form) return;
  const boxes = () => Array.from(form.querySelectorAll('input[name="company_ids"]'));
  const count = document.getElementById("selection-count");
  const queries = Number(count?.dataset.queries || 4);
  function refresh() {
    const chosen = boxes().filter((box) => box.checked);
    const missing = chosen.filter((box) => box.dataset.noEmail).length;
    if (!count) return;
    const searches = chosen.length * queries;
    count.textContent = `${chosen.length} selected · about ${searches} searches${missing ? ` · ${missing} without email` : ""}`;
  }
  form.addEventListener("change", refresh);
  document.getElementById("select-none")?.addEventListener("click", () => {
    boxes().forEach((box) => { box.checked = false; });
    refresh();
  });
  function selectTop(n) {
    boxes().forEach((box, index) => { box.checked = index < n; });
    refresh();
  }
  document.getElementById("select-top")?.addEventListener("click", (event) => {
    selectTop(Number(event.currentTarget.dataset.count || 10));
  });
  document.getElementById("select-n")?.addEventListener("click", () => {
    const n = Number(document.getElementById("top-n")?.value || 5);
    selectTop(n);
  });
  refresh();
}

function setupProgress() {
  const root = document.getElementById("progress");
  if (!root) return;
  const url = root.dataset.url;
  const results = root.dataset.results;
  async function tick() {
    const response = await fetch(url);
    if (response.status === 401) {
      window.location = "/login";
      return;
    }
    const data = await response.json();
    root.innerHTML = "";
    if (!data.companies.length) {
      root.innerHTML = "<p class='hint'>Nothing is queued.</p>";
    }
    data.companies.forEach((company) => {
      const row = document.createElement("article");
      row.className = "card";
      const title = document.createElement("strong");
      const link = document.createElement("a");
      link.href = `/companies/${company.id}`;
      link.textContent = company.name;
      title.appendChild(link);
      const step = document.createElement("div");
      step.className = "sub";
      step.textContent = `${(company.status || "").split("_").join(" ")} — ${company.step || ""}`;
      row.append(title, step);
      if (company.error) {
        const err = document.createElement("p");
        err.className = "banner bad";
        err.textContent = company.error;
        row.appendChild(err);
      }
      root.appendChild(row);
    });
    const lede = document.getElementById("progress-lede");
    if (data.done && lede) {
      lede.innerHTML = `Finished. <a href="${results}">Review the drafts</a>.`;
      return;
    }
    window.setTimeout(tick, 1500);
  }
  tick();
}

function setupCounts() {
  const body = document.getElementById("body");
  const follow = document.getElementById("followup_body");
  if (!body) return;
  const bodyOut = document.getElementById("body-count");
  const followOut = document.getElementById("follow-count");
  function refresh() {
    if (bodyOut) bodyOut.textContent = `${wordCount(body.value)} words in the body (aim 60–90, max 100).`;
    if (followOut) followOut.textContent = `${wordCount(follow.value)} words in the follow-up (max 40).`;
  }
  body.addEventListener("input", refresh);
  follow?.addEventListener("input", refresh);
  refresh();
}

setupSelection();
setupProgress();
setupCounts();
