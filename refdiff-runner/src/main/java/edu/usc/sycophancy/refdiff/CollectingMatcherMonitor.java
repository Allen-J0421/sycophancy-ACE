package edu.usc.sycophancy.refdiff;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import refdiff.core.cst.CstNode;
import refdiff.core.diff.CstComparatorMonitor;

/**
 * Collects matcher discard events from RefDiff 2.0.0 {@link CstComparatorMonitor}.
 */
public final class CollectingMatcherMonitor implements CstComparatorMonitor {

    public static final class DiscardedMatch {
        public final CstNode before;
        public final CstNode after;
        public final double score;

        DiscardedMatch(CstNode before, CstNode after, double score) {
            this.before = before;
            this.after = after;
            this.score = score;
        }
    }

    private final List<String> lines = new ArrayList<>();
    private final List<DiscardedMatch> discardedMatches = new ArrayList<>();

    public List<String> getLines() {
        return Collections.unmodifiableList(lines);
    }

    public List<DiscardedMatch> getDiscardedMatches() {
        return Collections.unmodifiableList(discardedMatches);
    }

    @Override
    public void reportDiscardedMatch(CstNode n1, CstNode n2, double score) {
        lines.add(String.format("Discarded match with score %.3f\t {%s} {%s}", score, n1, n2));
        discardedMatches.add(new DiscardedMatch(n1, n2, score));
    }

    @Override
    public void reportDiscardedConflictingMatch(CstNode n1, CstNode n2) {
        lines.add(String.format("Discarded match by conflict\t {%s} {%s}", n1, n2));
    }

    @Override
    public void reportDiscardedExtract(CstNode n1, CstNode n2, double score) {
        lines.add(String.format("Discarded EXTRACT with score %.3f\t {%s} {%s}", score, n1, n2));
    }

    @Override
    public void reportDiscardedInline(CstNode n1, CstNode n2, double score) {
        lines.add(String.format("Discarded INLINE with score %.3f\t {%s} {%s}", score, n1, n2));
    }
}
