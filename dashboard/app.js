(function () {
  const DATA = window.__EXPERIMENT_DATA__;
  const missingMsg =
    DATA.missing_artifact_msg ||
    "No artifacts for this step (re-run experiment after dashboard support).";

  let activeModelIndex = 0;
  let selectedRun = 1;
  let chart = null;

  const els = {
    title: document.getElementById("exp-title"),
    tabs: document.getElementById("model-tabs"),
    stepLabel: document.getElementById("step-label"),
    stepMeta: document.getElementById("step-meta"),
    prevBtn: document.getElementById("prev-btn"),
    nextBtn: document.getElementById("next-btn"),
    diffPre: document.getElementById("diff-pre"),
    responsePre: document.getElementById("response-pre"),
    reasoningBtn: document.getElementById("reasoning-btn"),
    reasoningDialog: document.getElementById("reasoning-dialog"),
    reasoningPre: document.getElementById("reasoning-pre"),
    reasoningClose: document.getElementById("reasoning-close"),
    codexBtn: document.getElementById("codex-btn"),
    codexDialog: document.getElementById("codex-dialog"),
    codexPre: document.getElementById("codex-pre"),
    codexClose: document.getElementById("codex-close"),
    canvas: document.getElementById("chart"),
  };

  function activeModel() {
    return DATA.models[activeModelIndex];
  }

  function activeStep() {
    const model = activeModel();
    return model.steps.find((s) => s.run === selectedRun) || model.steps[0];
  }

  function escapeHtml(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function setPre(el, text, isEmpty) {
    if (isEmpty) {
      el.innerHTML = '<span class="empty-msg">' + escapeHtml(text) + "</span>";
    } else {
      el.textContent = text;
    }
  }

  function diffLineClass(line) {
    if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ")) {
      return "diff-meta";
    }
    if (line.startsWith("@@")) {
      return "diff-hunk";
    }
    if (line.startsWith("+")) {
      return "diff-add";
    }
    if (line.startsWith("-")) {
      return "diff-del";
    }
    return "diff-ctx";
  }

  function renderDiffHtml(diff) {
    const lines = diff.split("\n");
    return lines
      .map((line) => {
        const cls = diffLineClass(line);
        const content = escapeHtml(line) || " ";
        return '<span class="diff-line ' + cls + '">' + content + "</span>";
      })
      .join("");
  }

  function setDiffPre(el, text, isEmpty) {
    if (isEmpty) {
      el.innerHTML = '<span class="empty-msg">' + escapeHtml(text) + "</span>";
    } else {
      el.innerHTML = renderDiffHtml(text);
    }
  }

  function selectRun(run) {
    selectedRun = run;
    updatePanels();
  }

  function updatePanels() {
    const step = activeStep();
    if (!step) return;

    const model = activeModel();
    const total = model.steps.length;
    const idx = model.steps.findIndex((s) => s.run === selectedRun) + 1;

    els.stepLabel.textContent = `Step ${idx} of ${total} (run ${step.run})`;
    els.stepMeta.textContent =
      `+${step.lines_added} / -${step.lines_deleted} (total ${step.lines_total}) · ` +
      `${step.duration_s}s · exit ${step.exit_code}` +
      (step.timed_out ? " · timed out" : "");

    els.prevBtn.disabled = idx <= 1;
    els.nextBtn.disabled = idx >= total;

    const hasArtifacts = step.has_artifacts;
    if (!hasArtifacts) {
      setDiffPre(els.diffPre, missingMsg, true);
      setPre(els.responsePre, missingMsg, true);
    } else {
      setDiffPre(els.diffPre, step.diff || "(empty diff)", !step.diff);
      setPre(els.responsePre, step.response || "(empty response)", !step.response);
    }
    els.reasoningBtn.disabled = !step.reasoning;
    els.codexBtn.disabled = !step.codex_jsonl;
  }

  function buildChart() {
    const model = activeModel();
    const labels = model.steps.map((s) => String(s.run));
    const values = model.steps.map((s) => s.lines_total);

    if (chart) {
      chart.destroy();
    }

    chart = new Chart(els.canvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: model.label,
            data: values,
            borderColor: model.color,
            backgroundColor: model.color,
            pointBackgroundColor: model.color,
            pointBorderColor: model.color,
            pointRadius: 5,
            pointBorderWidth: 1,
            borderWidth: 1.5,
            tension: 0.1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        onClick: (_evt, elements) => {
          if (!elements.length) return;
          const idx = elements[0].index;
          selectRun(model.steps[idx].run);
        },
        plugins: {
          legend: { display: false },
          title: {
            display: true,
            text: "Lines total changed per refactoring run",
            font: { size: 14 },
          },
        },
        scales: {
          x: {
            title: { display: true, text: "Refactoring iteration (run)" },
            ticks: { stepSize: 1 },
          },
          y: {
            title: { display: true, text: "Lines total changed" },
            beginAtZero: true,
          },
        },
      },
    });
  }

  function renderTabs() {
    els.tabs.innerHTML = "";
    DATA.models.forEach((model, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "model-tab" + (i === activeModelIndex ? " active" : "");
      btn.textContent = model.label + (model.stamp ? ` (${model.stamp.slice(0, 8)}…)` : "");
      btn.title = model.csv;
      btn.addEventListener("click", () => {
        activeModelIndex = i;
        selectedRun = DATA.models[i].steps[0]?.run || 1;
        renderTabs();
        buildChart();
        updatePanels();
      });
      els.tabs.appendChild(btn);
    });
  }

  function initReasoningDialog() {
    els.reasoningBtn.addEventListener("click", () => {
      const step = activeStep();
      if (!step?.reasoning) return;
      els.reasoningPre.textContent = step.reasoning;
      els.reasoningDialog.showModal();
    });
    els.reasoningClose.addEventListener("click", () => els.reasoningDialog.close());
  }

  function initCodexDialog() {
    els.codexBtn.addEventListener("click", () => {
      const step = activeStep();
      if (!step?.codex_jsonl) return;
      els.codexPre.textContent = step.codex_jsonl;
      els.codexDialog.showModal();
    });
    els.codexClose.addEventListener("click", () => els.codexDialog.close());
  }

  function initNav() {
    els.prevBtn.addEventListener("click", () => {
      const model = activeModel();
      const idx = model.steps.findIndex((s) => s.run === selectedRun);
      if (idx > 0) {
        selectRun(model.steps[idx - 1].run);
      }
    });

    els.nextBtn.addEventListener("click", () => {
      const model = activeModel();
      const idx = model.steps.findIndex((s) => s.run === selectedRun);
      if (idx >= 0 && idx < model.steps.length - 1) {
        selectRun(model.steps[idx + 1].run);
      }
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") els.prevBtn.click();
      if (e.key === "ArrowRight") els.nextBtn.click();
    });
  }

  function init() {
    if (!DATA.models.length) {
      els.title.textContent = DATA.experiment + " (no data)";
      return;
    }

    els.title.textContent = "Experiment: " + DATA.experiment.toUpperCase();
    selectedRun = DATA.models[0].steps[0]?.run || 1;
    renderTabs();
    initNav();
    initReasoningDialog();
    initCodexDialog();
    buildChart();
    updatePanels();
  }

  init();
})();
