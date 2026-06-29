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
    prompterColumn: document.getElementById("prompter-column"),
    codingColumnHeader: document.getElementById("coding-column-header"),
    codingOnlyActions: document.getElementById("coding-only-actions"),
    prompterPre: document.getElementById("prompter-pre"),
    prompterMessagesBtn: document.getElementById("prompter-messages-btn"),
    prompterJsonlBtn: document.getElementById("prompter-jsonl-btn"),
    prompterMessagesDialog: document.getElementById("prompter-messages-dialog"),
    prompterMessagesPre: document.getElementById("prompter-messages-pre"),
    prompterMessagesClose: document.getElementById("prompter-messages-close"),
    prompterJsonlDialog: document.getElementById("prompter-jsonl-dialog"),
    prompterJsonlPre: document.getElementById("prompter-jsonl-pre"),
    prompterJsonlClose: document.getElementById("prompter-jsonl-close"),
    responseColumns: document.getElementById("response-columns"),
    reasoningBtn: document.getElementById("reasoning-btn"),
    reasoningBtnColumn: document.getElementById("reasoning-btn-column"),
    reasoningDialog: document.getElementById("reasoning-dialog"),
    reasoningPre: document.getElementById("reasoning-pre"),
    reasoningClose: document.getElementById("reasoning-close"),
    codexBtn: document.getElementById("codex-btn"),
    codexBtnColumn: document.getElementById("codex-btn-column"),
    codexDialog: document.getElementById("codex-dialog"),
    codexPre: document.getElementById("codex-pre"),
    codexClose: document.getElementById("codex-close"),
    refdiffPre: document.getElementById("refdiff-pre"),
    matcherDiscardedBtn: document.getElementById("matcher-discarded-btn"),
    matcherDiscardedDialog: document.getElementById("matcher-discarded-dialog"),
    matcherDiscardedPre: document.getElementById("matcher-discarded-pre"),
    matcherDiscardedClose: document.getElementById("matcher-discarded-close"),
    refdiffBtn: document.getElementById("refdiff-btn"),
    refdiffDialog: document.getElementById("refdiff-dialog"),
    refdiffDialogPre: document.getElementById("refdiff-dialog-pre"),
    refdiffClose: document.getElementById("refdiff-close"),
    signalsPre: document.getElementById("signals-pre"),
    setsBtn: document.getElementById("sets-btn"),
    setsDialog: document.getElementById("sets-dialog"),
    setsDialogBody: document.getElementById("sets-dialog-body"),
    setsClose: document.getElementById("sets-close"),
    canvas: document.getElementById("chart"),
  };

  function stepHasPrompter(step) {
    return Boolean(
      step &&
        (step.prompter_prompt ||
          step.prompter_transcript ||
          step.prompter_jsonl)
    );
  }

  function setAgentResponseLayout(step) {
    const prompterMode = stepHasPrompter(step);
    if (els.prompterColumn) {
      els.prompterColumn.hidden = !prompterMode;
    }
    if (els.codingColumnHeader) {
      els.codingColumnHeader.hidden = !prompterMode;
    }
    if (els.codingOnlyActions) {
      els.codingOnlyActions.hidden = prompterMode;
    }
    if (els.responseColumns) {
      els.responseColumns.classList.toggle("response-columns-prompter", prompterMode);
    }
  }

  function setReasoningButtonsDisabled(disabled) {
    if (els.reasoningBtn) els.reasoningBtn.disabled = disabled;
    if (els.reasoningBtnColumn) els.reasoningBtnColumn.disabled = disabled;
  }

  function agentJsonlForStep(step) {
    return step?.agent_jsonl || step?.codex_jsonl || "";
  }

  function agentJsonlLabel(step) {
    const kind = step?.agent_kind;
    if (kind === "claude") return "claude.jsonl";
    return "codex.jsonl";
  }

  function setCodexButtonsDisabled(disabled) {
    if (els.codexBtn) els.codexBtn.disabled = disabled;
    if (els.codexBtnColumn) els.codexBtnColumn.disabled = disabled;
  }

  function updateAgentJsonlButtons(step) {
    const label = agentJsonlLabel(step);
    if (els.codexBtn) els.codexBtn.textContent = label;
    if (els.codexBtnColumn) els.codexBtnColumn.textContent = label;
    setCodexButtonsDisabled(!agentJsonlForStep(step));
  }

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
    let typeLabel = type;
    if (type === "SAME" && rel.same_edited != null) {
      typeLabel = rel.same_edited ? "SAME (Edited)" : "SAME (Unchanged)";
    }
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
      escapeHtml(typeLabel) +
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
    const nSameEdited = intOrZero(record.n_same_edited);
    const summaryText =
      `RefDiff: ${nMatching} matching, ${nNonMatching} non-matching, ${nNoRelationship} no relationship (${nTotal} total)` +
      (record.n_same_edited != null ? ` · Same edited: ${nSameEdited}` : "");

    const summary =
      '<div class="refdiff-summary">' +
      escapeHtml(summaryText) +
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

  const SIGNAL_META = [
    ["S0", "First stop turn"],
    ["S1", "Pre-convergence churn"],
    ["S2", "Post-convergence modification"],
    ["S3", "Line-change volatility"],
    ["S4", "Feature rollback/removal"],
    ["S5", "Reimplementation loop"],
    ["S6", "Patch-region recurrence"],
    ["S7", "Verbal-refusal edit rate"],
  ];

  function fmtNum(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return Number.isInteger(n) ? String(n) : n.toFixed(3);
  }

  function fmtSignalVal(id, entry) {
    if (!entry || entry.cont === undefined) return "—";
    const n = Number(entry.cont);
    if (!Number.isFinite(n)) return "—";
    let text =
      id === "S0"
        ? String(Math.round(n))
        : Number.isInteger(n)
          ? String(n)
          : n.toFixed(3);
    if (id === "S0" && entry.never_stopped) text += "\u2020";
    return text;
  }

  function renderSignalsHtml(model, step) {
    const signals = model.signals;
    if (!signals) {
      return (
        '<span class="empty-msg">No signals for this experiment. ' +
        "Run: python compute_signals.py</span>"
      );
    }

    const values = signals.values || {};
    const t0 = signals.t0;
    const numTurns = signals.num_turns;
    const t0Text =
      t0 != null && numTurns != null && t0 > numTurns
        ? "never (no no-change turn)"
        : `run ${t0}`;
    const l0Text =
      signals.L0_ok === false
        ? `${signals.L0} (unavailable)`
        : String(signals.L0);

    let meta =
      '<div class="signals-meta">' +
      `<span><strong>t₀</strong>: ${escapeHtml(t0Text)}</span>` +
      `<span><strong>L₀</strong>: ${escapeHtml(l0Text)} LOC</span>` +
      `<span><strong>turns</strong>: ${escapeHtml(String(numTurns))}</span>`;
    if (signals.skipped_turns) {
      meta += `<span><strong>skipped</strong>: ${escapeHtml(String(signals.skipped_turns))}</span>`;
    }
    meta += "</div>";

    const rolling = step && step.signal ? step.signal.rolling : null;
    const hasRolling = rolling && typeof rolling === "object";

    function flagCell(entry) {
      if (!entry || entry.bin === undefined) {
        return '<td class="signal-val">—</td>';
      }
      const on = Number(entry.bin);
      const cls = on ? "signal-flag on" : "signal-flag off";
      return `<td><span class="${cls}">${on ? "1" : "0"}</span></td>`;
    }

    let rows = "";
    SIGNAL_META.forEach(([id, name]) => {
      const entry = values[id] || {};
      rows +=
        "<tr>" +
        `<td class="signal-id">${id}</td>` +
        `<td class="signal-name">${escapeHtml(name)}</td>`;
      if (hasRolling) {
        const rentry = rolling[id] || {};
        rows +=
          `<td class="signal-val">${escapeHtml(fmtSignalVal(id, rentry))}</td>` +
          flagCell(rentry);
      }
      rows +=
        `<td class="signal-val">${escapeHtml(fmtSignalVal(id, entry))}</td>` +
        flagCell(entry);
      rows += "</tr>";
    });

    const runHeader = hasRolling
      ? `<th colspan="2">Run ${escapeHtml(String(step.run))}</th>`
      : "";
    const table =
      '<table class="signals-table">' +
      "<thead><tr>" +
      "<th>ID</th><th>Signal</th>" +
      runHeader +
      '<th colspan="2">Final</th>' +
      "</tr></thead>" +
      `<tbody>${rows}</tbody></table>`;

    let stepBlock = "";
    if (step && step.signal) {
      const s = step.signal;
      const sets = s.sets || {};
      const verbalDecline = sets.verbal_decline && sets.verbal_decline[0] === "1";
      const hypocritical = sets.hypocritical_refusal && sets.hypocritical_refusal[0] === "1";
      stepBlock =
        '<div class="signals-step">' +
        `<div class="signals-step-title">Run ${step.run} breakdown</div>` +
        '<div class="signals-step-grid">' +
        `<span>LC: ${fmtNum(s.LC)}</span>` +
        `<span>f₁: ${fmtNum(s.f1)}</span>` +
        `<span>N⁺ (new): ${fmtNum(s.N_plus)}</span>` +
        `<span>N⁻ (del): ${fmtNum(s.N_minus)}</span>` +
        `<span>N⁻ agent: ${fmtNum(s.N_minus_new)}</span>` +
        `<span>touched: ${fmtNum(s.T_touched)}</span>` +
        `<span>|C|: ${fmtNum(s.C_size)}</span>` +
        `<span>ρ: ${fmtNum(s.rho)}</span>` +
        (sets.verbal_decline
          ? `<span>verbal decline: ${verbalDecline ? "yes" : "no"}</span>`
          : "") +
        (sets.hypocritical_refusal
          ? `<span>hypocritical refusal: ${hypocritical ? "yes" : "no"}</span>`
          : "") +
        "</div></div>";
    }

    return meta + table + stepBlock;
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
    setAgentResponseLayout(step);
    if (!hasArtifacts) {
      setDiffPre(els.diffPre, missingMsg, true);
      setPre(els.responsePre, missingMsg, true);
      if (els.prompterPre) {
        setPre(els.prompterPre, missingMsg, true);
      }
    } else {
      setDiffPre(els.diffPre, step.diff || "(empty diff)", !step.diff);
      setPre(els.responsePre, step.response || "(empty response)", !step.response);
      if (els.prompterPre) {
        const prompterText =
          step.prompter_prompt ||
          step.prompter_transcript ||
          "(empty prompter response)";
        setPre(els.prompterPre, prompterText, !step.prompter_prompt);
      }
    }
    setReasoningButtonsDisabled(!step.reasoning);
    updateAgentJsonlButtons(step);
    if (els.prompterMessagesBtn) {
      els.prompterMessagesBtn.disabled = !step.prompter_transcript;
    }
    if (els.prompterJsonlBtn) {
      els.prompterJsonlBtn.disabled = !step.prompter_jsonl;
    }
    if (els.matcherDiscardedBtn) {
      els.matcherDiscardedBtn.disabled = !step.refdiff;
    }
    els.refdiffBtn.disabled = !step.refdiff;
    if (els.setsBtn) {
      els.setsBtn.disabled = !(step.signal && step.signal.sets);
    }

    if (step.refdiff) {
      els.refdiffPre.innerHTML = renderRefdiffHtml(step.refdiff);
    } else {
      els.refdiffPre.innerHTML =
        '<span class="empty-msg">No RefDiff data for this experiment. Run: python run_refdiff.py --repo &lt;target&gt;</span>';
    }

    if (els.signalsPre) {
      els.signalsPre.innerHTML = renderSignalsHtml(model, step);
    }
  }

  function buildChart() {
    const model = activeModel();
    const labels = model.steps.map((s) => String(s.run));
    const values = model.steps.map((s) => s.lines_total);

    const t0 = model.signals ? model.signals.t0 : null;
    const pointColors = model.steps.map((s) =>
      t0 != null && s.run === t0 ? "#d62728" : model.color
    );
    const pointRadii = model.steps.map((s) =>
      t0 != null && s.run === t0 ? 7 : 5
    );

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
            pointBackgroundColor: pointColors,
            pointBorderColor: pointColors,
            pointRadius: pointRadii,
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
    function openReasoningDialog() {
      const step = activeStep();
      if (!step?.reasoning) return;
      els.reasoningPre.textContent = step.reasoning;
      els.reasoningDialog.showModal();
    }
    if (els.reasoningBtn) {
      els.reasoningBtn.addEventListener("click", openReasoningDialog);
    }
    if (els.reasoningBtnColumn) {
      els.reasoningBtnColumn.addEventListener("click", openReasoningDialog);
    }
    els.reasoningClose.addEventListener("click", () => els.reasoningDialog.close());
  }

  function initCodexDialog() {
    function openCodexDialog() {
      const step = activeStep();
      const agentJsonl = agentJsonlForStep(step);
      if (!agentJsonl) return;
      els.codexPre.textContent = formatJsonl(agentJsonl);
      els.codexDialog.showModal();
    }
    if (els.codexBtn) {
      els.codexBtn.addEventListener("click", openCodexDialog);
    }
    if (els.codexBtnColumn) {
      els.codexBtnColumn.addEventListener("click", openCodexDialog);
    }
    els.codexClose.addEventListener("click", () => els.codexDialog.close());
  }

  function initPrompterDialogs() {
    if (els.prompterMessagesBtn) {
      els.prompterMessagesBtn.addEventListener("click", () => {
        const step = activeStep();
        if (!step?.prompter_transcript) return;
        els.prompterMessagesPre.textContent = step.prompter_transcript;
        els.prompterMessagesDialog.showModal();
      });
    }
    if (els.prompterMessagesClose) {
      els.prompterMessagesClose.addEventListener("click", () =>
        els.prompterMessagesDialog.close()
      );
    }
    if (els.prompterJsonlBtn) {
      els.prompterJsonlBtn.addEventListener("click", () => {
        const step = activeStep();
        if (!step?.prompter_jsonl) return;
        els.prompterJsonlPre.textContent = formatJsonl(step.prompter_jsonl);
        els.prompterJsonlDialog.showModal();
      });
    }
    if (els.prompterJsonlClose) {
      els.prompterJsonlClose.addEventListener("click", () =>
        els.prompterJsonlDialog.close()
      );
    }
  }

  function formatMatcherDiscardedText(step) {
    const record = step.refdiff;
    const run = step.run;
    const commit = (record.commit_sha || "").trim();
    const header = `## run ${String(run).padStart(3, "0")} commit ${commit}`;
    const lines = Array.isArray(record.matcher_discarded) ? record.matcher_discarded : [];
    if (lines.length === 0) {
      return `${header}\n\nNo discarded matcher candidates for this turn.`;
    }
    const logPath = record.matcher_log ? `\n\n# log: ${record.matcher_log}` : "";
    return `${header}\n\n${lines.join("\n")}${logPath}`;
  }

  function initMatcherDiscardedDialog() {
    if (!els.matcherDiscardedBtn) return;
    els.matcherDiscardedBtn.addEventListener("click", () => {
      const step = activeStep();
      if (!step?.refdiff) return;
      els.matcherDiscardedPre.textContent = formatMatcherDiscardedText(step);
      els.matcherDiscardedDialog.showModal();
    });
    els.matcherDiscardedClose.addEventListener("click", () =>
      els.matcherDiscardedDialog.close()
    );
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

  const SETS_CUMULATIVE = new Set([
    "universe",
    "tracked",
    "s5_loops",
    "s5_loops_exact",
    "s5_loops_refdiff",
    "Nt",
  ]);

  const SETS_META = [
    ["Nt", "N_t — lineage roots in current snapshot"],
    ["universe", "U — lineage-root universe (union through this turn)"],
    ["tracked", "H_t — lineage roots ever changed"],
    ["s5_loops", "S5 — unified cluster IDs with present-absent-present (layer 1 + 2)"],
    ["s5_loops_exact", "S5 layer 1 — exact lineage-root P-A-P only"],
    ["s5_loops_refdiff", "S5 layer 2 — loops detected only via RefDiff soft links"],
    ["s5_refdiff_links", "S5 layer 2 — cross-turn RefDiff links active this turn"],
    ["C", "Changed this turn (C_t = N+ union N- union touched)"],
    ["recurring", "Recurring lineage roots (C_t roots already in H_{t-1})"],
    ["N_plus", "N+ — completely new nodes"],
    ["N_minus", "N- — completely deleted nodes"],
    ["N_minus_new", "N- agent-created — deleted nodes with no N0 lineage (S4)"],
    ["N_minus_baseline", "N- baseline — deleted nodes excluded from S4 (have N0 lineage)"],
    ["T_touched", "Touched — pre-existing nodes edited"],
  ];

  function renderSetsList(items, currentTurn, lastTurn) {
    if (items.length === 0) {
      return '<div class="sets-empty">empty</div>';
    }
    return (
      '<ul class="sets-list">' +
      items
        .map((it) => {
          let cls = "";
          if (currentTurn.has(it)) {
            cls = "sets-current-turn";
          } else if (lastTurn.has(it)) {
            cls = "sets-last-turn";
          }
          return `<li class="${cls}">${escapeHtml(it)}</li>`;
        })
        .join("") +
      "</ul>"
    );
  }

  function renderSetsHtml(step, model) {
    const sets = step && step.signal ? step.signal.sets : null;
    if (!sets) {
      return '<div class="empty-msg">No tracked sets for this run.</div>';
    }
    const currentTurn = new Set(Array.isArray(sets.C) ? sets.C : []);
    const stepIdx = model.steps.findIndex((s) => s.run === step.run);
    const prevStep = stepIdx > 0 ? model.steps[stepIdx - 1] : null;
    const lastTurn = new Set(
      prevStep?.signal?.sets?.C && Array.isArray(prevStep.signal.sets.C)
        ? prevStep.signal.sets.C
        : []
    );
    let html =
      `<div class="sets-title">Run ${escapeHtml(String(step.run))} — structural sets</div>` +
      '<div class="sets-legend">' +
      '<span class="sets-legend-item sets-legend-current">This turn (C_t)</span>' +
      '<span class="sets-legend-item sets-legend-last">Last turn (C_{t-1})</span>' +
      "</div>";
    SETS_META.forEach(([key, label]) => {
      const items = Array.isArray(sets[key]) ? sets[key] : [];
      const cumulative = SETS_CUMULATIVE.has(key);
      html +=
        '<div class="sets-group' + (cumulative ? " sets-group-cumulative" : "") + '">' +
        `<div class="sets-group-head">${escapeHtml(label)} <span class="sets-count">(${items.length})</span></div>`;
      if (cumulative) {
        html += renderSetsList(items, currentTurn, lastTurn);
      } else {
        html += renderSetsList(items, new Set(items), new Set());
      }
      html += "</div>";
    });
    return html;
  }

  function initSetsDialog() {
    if (!els.setsBtn) return;
    els.setsBtn.addEventListener("click", () => {
      const step = activeStep();
      if (!step?.signal?.sets) return;
      els.setsDialogBody.innerHTML = renderSetsHtml(step, activeModel());
      els.setsDialog.showModal();
    });
    els.setsClose.addEventListener("click", () => els.setsDialog.close());
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
    initPrompterDialogs();
    initMatcherDiscardedDialog();
    initRefdiffDialog();
    initSetsDialog();
    buildChart();
    updatePanels();
  }

  init();
})();
