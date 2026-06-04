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
    refdiffPre: document.getElementById("refdiff-pre"),
    refdiffBtn: document.getElementById("refdiff-btn"),
    refdiffDialog: document.getElementById("refdiff-dialog"),
    refdiffDialogPre: document.getElementById("refdiff-dialog-pre"),
    refdiffClose: document.getElementById("refdiff-close"),
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

  function parseHunkHeader(line) {
    const match = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (!match) return null;
    return {
      oldLine: parseInt(match[1], 10),
      newLine: parseInt(match[2], 10),
    };
  }

  function renderDiffRow(oldNum, newNum, line, cls) {
    const oldGutter = oldNum != null ? String(oldNum) : "";
    const newGutter = newNum != null ? String(newNum) : "";
    const content = escapeHtml(line) || " ";
    return (
      '<div class="diff-row ' +
      cls +
      '">' +
      '<span class="diff-ln diff-ln-old">' +
      escapeHtml(oldGutter) +
      "</span>" +
      '<span class="diff-ln diff-ln-new">' +
      escapeHtml(newGutter) +
      "</span>" +
      '<span class="diff-content">' +
      content +
      "</span>" +
      "</div>"
    );
  }

  function renderDiffHtml(diff) {
    const lines = diff.split("\n");
    const rows = [];
    let oldLine = null;
    let newLine = null;

    for (const line of lines) {
      const cls = diffLineClass(line);

      if (line.startsWith("@@")) {
        const hunk = parseHunkHeader(line);
        if (hunk) {
          oldLine = hunk.oldLine;
          newLine = hunk.newLine;
        }
        rows.push(renderDiffRow(null, null, line, cls));
        continue;
      }

      if (line.startsWith("-") && !line.startsWith("---")) {
        rows.push(renderDiffRow(oldLine, null, line, cls));
        if (oldLine != null) oldLine++;
        continue;
      }

      if (line.startsWith("+") && !line.startsWith("+++")) {
        rows.push(renderDiffRow(null, newLine, line, cls));
        if (newLine != null) newLine++;
        continue;
      }

      if (cls === "diff-ctx") {
        rows.push(renderDiffRow(oldLine, newLine, line, cls));
        if (oldLine != null) oldLine++;
        if (newLine != null) newLine++;
        continue;
      }

      rows.push(renderDiffRow(null, null, line, cls));
    }

    return rows.join("");
  }

  function formatJsonl(text) {
    return text
      .split("\n")
      .map((line) => {
        const trimmed = line.trim();
        if (!trimmed) return "";
        try {
          return JSON.stringify(JSON.parse(trimmed), null, 2);
        } catch {
          return line;
        }
      })
      .filter((block) => block.length > 0)
      .join("\n\n");
  }

  function formatNode(node) {
    if (!node) return "(unknown)";
    const kind = node.kind || "";
    const localName = node.localName || "";
    const file = node.file || "";
    const line = node.line != null ? node.line : "";
    const label = [kind, localName].filter(Boolean).join(" ");
    if (file) {
      return `${label}  @ ${file}:${line}`;
    }
    return label || "(unknown)";
  }

  function refdiffDescription(rel) {
    if (rel.similarity != null && rel.description_with_score) {
      return rel.description_with_score;
    }
    return rel.description_standard || "";
  }

  function formatRefdiffCell(record) {
    if (!record) return "";
    if (!record.refdiff_ok) {
      const msg = (record.error_message || "unknown error").trim();
      return `RefDiff failed\n${msg}`;
    }

    const nRef = intOrZero(record.n_refactorings);
    const nSame = intOrZero(record.n_same);
    const nTotal = intOrZero(record.n_relationships_total);
    const refactorings = record.refactorings || [];
    const sameRelationships = record.same_relationships || [];

    const lines = [];
    lines.push(
      `RefDiff: ${nRef} refactoring, ${nSame} non-refactoring relationship (${nTotal} total)`
    );

    for (const rel of refactorings) {
      const desc = refdiffDescription(rel);
      if (desc) lines.push(desc);
    }

    if (refactorings.length > 0) {
      lines.push("");
      lines.push("Refactoring Relationship (RefDiff-detected structural refactorings)");
      for (const rel of refactorings) {
        lines.push(`  ${rel.type || "UNKNOWN"}`);
        lines.push(`    before: ${formatNode(rel.before)}`);
        lines.push(`    after:  ${formatNode(rel.after)}`);
      }
    }

    if (sameRelationships.length > 0) {
      lines.push("");
      lines.push('Non-refactoring relationships ("SAME")');
      for (const rel of sameRelationships) {
        const label = (rel.before && rel.before.localName) || rel.type || "SAME";
        lines.push(`  ${label}`);
        lines.push(`    before: ${formatNode(rel.before)}`);
        lines.push(`    after:  ${formatNode(rel.after)}`);
      }
    }

    const nearMisses = record.near_misses || [];
    if (nearMisses.length > 0) {
      lines.push("");
      lines.push("Near-miss candidates (below RefDiff threshold; inferred, not detected)");
      for (const nm of nearMisses) {
        const score = nm.score != null ? Number(nm.score).toFixed(3) : "?";
        lines.push(`  (match discarded)  ${nm.type || "UNKNOWN"}  score=${score}`);
        lines.push(`    before: ${formatNode(nm.before)}`);
        lines.push(`    after:  ${formatNode(nm.after)}`);
      }
    }

    return lines.join("\n");
  }

  function intOrZero(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : 0;
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
    let meta =
      `+${step.lines_added} / -${step.lines_deleted} (total ${step.lines_total}) · ` +
      `${step.duration_s}s · exit ${step.exit_code}` +
      (step.timed_out ? " · timed out" : "");
    if (step.refdiff_hover) {
      meta += ` · RefDiff: ${step.refdiff_hover}`;
    }
    els.stepMeta.textContent = meta;

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
    els.refdiffBtn.disabled = !step.refdiff;

    if (step.refdiff) {
      setPre(els.refdiffPre, formatRefdiffCell(step.refdiff), false);
    } else {
      setPre(
        els.refdiffPre,
        "No RefDiff data for this experiment. Run: python run_refdiff.py --repo <target>",
        true
      );
    }
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
        interaction: {
          mode: "nearest",
          intersect: true,
        },
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
          tooltip: {
            callbacks: {
              afterBody(tooltipItems) {
                if (!tooltipItems.length) return [];
                const step = model.steps[tooltipItems[0].dataIndex];
                if (!step || !step.refdiff_hover) return [];
                return ["RefDiff: " + step.refdiff_hover];
              },
            },
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
      els.codexPre.textContent = formatJsonl(step.codex_jsonl);
      els.codexDialog.showModal();
    });
    els.codexClose.addEventListener("click", () => els.codexDialog.close());
  }

  function initRefdiffDialog() {
    els.refdiffBtn.addEventListener("click", () => {
      const step = activeStep();
      if (!step?.refdiff) return;
      els.refdiffDialogPre.textContent = JSON.stringify(step.refdiff, null, 2);
      els.refdiffDialog.showModal();
    });
    els.refdiffClose.addEventListener("click", () => els.refdiffDialog.close());
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
    initRefdiffDialog();
    buildChart();
    updatePanels();
  }

  init();
})();
