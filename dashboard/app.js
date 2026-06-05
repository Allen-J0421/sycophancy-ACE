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
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function escapeAttr(text) {
    return escapeHtml(text).replace(/"/g, "&quot;");
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

  function renderNodeHtml(node) {
    if (!node) {
      return '<span class="empty-msg">(unknown)</span>';
    }

    const label =
      node.kind && node.localName
        ? `${node.kind}: ${node.localName}`
        : node.kind || node.localName || "";
    const file = node.file || "";
    const line = node.line != null ? String(node.line) : "";
    const path = Array.isArray(node.path) ? node.path.join(" / ") : "";

    return (
      '<div class="refdiff-node">' +
      '<div class="refdiff-node-title">' +
      escapeHtml(label || "(unknown)") +
      "</div>" +
      (file
        ? '<div class="refdiff-node-location">' +
          escapeHtml(file + (line ? ":" + line : "")) +
          "</div>"
        : "") +
      (path && path !== file
        ? '<div class="refdiff-node-path">' + escapeHtml(path) + "</div>"
        : "") +
      "</div>"
    );
  }

  function relationshipDescription(rel) {
    if (rel.similarity != null && rel.description_with_score) {
      return rel.description_with_score;
    }
    return rel.description_standard || "";
  }

  function renderRelationshipHtml(rel, fallbackMatching) {
    const isMatching =
      rel.is_matching === true || (rel.is_matching == null && fallbackMatching === true);
    const className = isMatching ? "matching" : "non-matching";
    const label = isMatching ? "Matching" : "Non-Matching";
    const type = rel.type || "UNKNOWN";
    const description = relationshipDescription(rel);
    const similarity =
      rel.similarity != null
        ? '<div class="refdiff-similarity">score ' + escapeHtml(Number(rel.similarity).toFixed(3)) + "</div>"
        : "";

    return (
      '<div class="refdiff-relationship" title="' +
      escapeAttr(description) +
      '">' +
      '<span class="refdiff-badge ' +
      className +
      '">' +
      label +
      "</span>" +
      '<span class="refdiff-type">' +
      escapeHtml(type) +
      "</span>" +
      similarity +
      "</div>"
    );
  }

  function renderNoRelationshipHtml(label) {
    return (
      '<div class="refdiff-relationship">' +
      '<span class="refdiff-badge no-relationship">No Relationship</span>' +
      '<span class="refdiff-type">' +
      escapeHtml(label) +
      "</span>" +
      "</div>"
    );
  }

  function renderRelationshipRow(beforeNode, relationshipHtml, afterNode) {
    return (
      "<tr>" +
      "<td>" +
      renderNodeHtml(beforeNode) +
      "</td>" +
      "<td>" +
      relationshipHtml +
      "</td>" +
      "<td>" +
      renderNodeHtml(afterNode) +
      "</td>" +
      "</tr>"
    );
  }

  function renderNodeRelationshipRows(record) {
    const nodeRelationships = record.node_relationships || {};
    const entries = Object.entries(nodeRelationships);
    const result = { rows: [], matching: 0, nonMatching: 0, noRelationship: 0 };
    const seenBefore = new Set();
    const seenAfter = new Set();

    for (const [key, entry] of entries) {
      if (!key.startsWith("before:")) continue;
      const beforeNode = entry.node;
      const relationships = entry.relationships || [];
      if (relationships.length === 0) continue;

      seenBefore.add(key);
      for (const rel of relationships) {
        const afterKey = rel.counterpart_key;
        const afterEntry = nodeRelationships[afterKey] || {};
        if (afterKey) seenAfter.add(afterKey);
        if (rel.is_matching === true) {
          result.matching++;
        } else {
          result.nonMatching++;
        }
        result.rows.push(
          renderRelationshipRow(
            beforeNode,
            renderRelationshipHtml(rel, rel.is_matching === true),
            afterEntry.node
          )
        );
      }
    }

    for (const [key, entry] of entries) {
      if (!key.startsWith("before:") || seenBefore.has(key)) continue;
      result.noRelationship++;
      result.rows.push(renderRelationshipRow(entry.node, renderNoRelationshipHtml("Node Deleted"), null));
    }

    for (const [key, entry] of entries) {
      if (!key.startsWith("after:") || seenAfter.has(key)) continue;
      result.noRelationship++;
      result.rows.push(renderRelationshipRow(null, renderNoRelationshipHtml("Node Added"), entry.node));
    }

    if (result.rows.length > 0 || entries.length > 0) {
      return result;
    }

    return renderFallbackRelationshipRows(record);
  }

  function renderFallbackRelationshipRows(record) {
    const matchingRelationships = record.matching_relationships || [];
    const nonMatchingRelationships = record.non_matching_relationships || [];
    const relationships = [
      ...nonMatchingRelationships.map((rel) => ({ rel, fallbackMatching: false })),
      ...matchingRelationships.map((rel) => ({ rel, fallbackMatching: true })),
    ];
    const seenBeforeIds = new Set();
    const seenAfterIds = new Set();
    const result = { rows: [], matching: 0, nonMatching: 0, noRelationship: 0 };

    for (const { rel, fallbackMatching } of relationships) {
      if (rel.before) seenBeforeIds.add(rel.before.id);
      if (rel.after) seenAfterIds.add(rel.after.id);
      if (rel.is_matching === true || fallbackMatching === true) {
        result.matching++;
      } else {
        result.nonMatching++;
      }
      result.rows.push(
        renderRelationshipRow(
          rel.before,
          renderRelationshipHtml(rel, fallbackMatching),
          rel.after
        )
      );
    }

    for (const node of record.nodes_before || []) {
      if (seenBeforeIds.has(node.id)) continue;
      result.noRelationship++;
      result.rows.push(renderRelationshipRow(node, renderNoRelationshipHtml("Node Deleted"), null));
    }

    for (const node of record.nodes_after || []) {
      if (seenAfterIds.has(node.id)) continue;
      result.noRelationship++;
      result.rows.push(renderRelationshipRow(null, renderNoRelationshipHtml("Node Added"), node));
    }

    return result;
  }

  function renderRefdiffHtml(record) {
    if (!record) return "";
    if (!record.refdiff_ok) {
      const msg = (record.error_message || "unknown error").trim();
      return (
        '<div class="empty-msg">RefDiff failed<br />' +
        escapeHtml(msg) +
        "</div>"
      );
    }

    const nNodesBefore = (record.nodes_before || []).length;
    const nNodesAfter = (record.nodes_after || []).length;
    const rowData = renderNodeRelationshipRows(record);
    const nMatching = rowData.matching;
    const nNonMatching = rowData.nonMatching;
    const nNoRelationship = rowData.noRelationship;
    const nTotal = nMatching + nNonMatching + nNoRelationship;

    const summary =
      '<div class="refdiff-summary">' +
      escapeHtml(
        `RefDiff: ${nMatching} matching, ${nNonMatching} non-matching, ${nNoRelationship} no relationship (${nTotal} total)`
      ) +
      '<span class="refdiff-summary-secondary">' +
      escapeHtml(`Nodes: ${nNodesBefore} before, ${nNodesAfter} after`) +
      "</span>" +
      "</div>";

    if (rowData.rows.length === 0) {
      return summary + '<div class="empty-msg">No nodes detected.</div>';
    }

    return (
      summary +
      '<table class="refdiff-table">' +
      "<thead><tr>" +
      "<th>Node before</th>" +
      "<th>Relationship</th>" +
      "<th>Node after</th>" +
      "</tr></thead>" +
      "<tbody>" +
      rowData.rows.join("") +
      "</tbody>" +
      "</table>"
    );
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
      els.refdiffPre.innerHTML = renderRefdiffHtml(step.refdiff);
    } else {
      els.refdiffPre.innerHTML =
        '<span class="empty-msg">No RefDiff data for this experiment. Run: python run_refdiff.py --repo &lt;target&gt;</span>';
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
            text: "Lines total changed per experiment run",
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
