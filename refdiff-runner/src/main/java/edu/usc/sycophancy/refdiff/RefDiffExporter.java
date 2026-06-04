package edu.usc.sycophancy.refdiff;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

import refdiff.core.cst.CstNode;
import refdiff.core.cst.Location;
import refdiff.core.diff.CstDiff;
import refdiff.core.diff.Relationship;
import refdiff.core.diff.RelationshipType;

/**
 * Builds a JSON-serializable map from a {@link CstDiff} and run metadata.
 */
public final class RefDiffExporter {

    private static final String PROP_NEAR_MISS_MIN = "refdiff.nearMiss.min";
    private static final String PROP_NEAR_MISS_MAX = "refdiff.nearMiss.max";
    private static final double DEFAULT_NEAR_MISS_MIN_SCORE = 0.3;
    private static final double DEFAULT_NEAR_MISS_MAX_SCORE = 0.5;

    private RefDiffExporter() {}

    static final class NearMissScoreBand {
        final double min;
        final double max;

        NearMissScoreBand(double min, double max) {
            this.min = min;
            this.max = max;
        }
    }

    /** Score band from JVM system properties (set by Gradle from run_refdiff.py / .env). */
    static NearMissScoreBand nearMissScoreBand() {
        double min = parsePropertyScore(PROP_NEAR_MISS_MIN, DEFAULT_NEAR_MISS_MIN_SCORE);
        double max = parsePropertyScore(PROP_NEAR_MISS_MAX, DEFAULT_NEAR_MISS_MAX_SCORE);
        if (min >= max) {
            return new NearMissScoreBand(DEFAULT_NEAR_MISS_MIN_SCORE, DEFAULT_NEAR_MISS_MAX_SCORE);
        }
        return new NearMissScoreBand(min, max);
    }

    private static double parsePropertyScore(String key, double defaultValue) {
        String raw = System.getProperty(key);
        if (raw == null || raw.isBlank()) {
            return defaultValue;
        }
        try {
            return Double.parseDouble(raw.trim());
        } catch (NumberFormatException e) {
            return defaultValue;
        }
    }

    public static Map<String, Object> buildRecord(
            String repoPath,
            String commitSha,
            String parentSha,
            CstDiff diff,
            boolean includeSame,
            List<String> matcherDiscarded,
            List<CollectingMatcherMonitor.DiscardedMatch> discardedMatches,
            long durationMs,
            boolean refdiffOk,
            String errorMessage) {

        Map<String, Object> record = new LinkedHashMap<>();
        record.put("repo_path", repoPath);
        record.put("commit_sha", commitSha);
        record.put("parent_sha", parentSha != null ? parentSha : "");
        record.put("refdiff_ok", refdiffOk);
        record.put("error_message", errorMessage != null ? errorMessage : "");
        record.put("duration_ms", durationMs);
        record.put("matcher_discarded", matcherDiscarded != null ? matcherDiscarded : List.of());
        NearMissScoreBand nearMissBand = nearMissScoreBand();

        if (!refdiffOk || diff == null) {
            record.put("n_refactorings", 0);
            record.put("n_same", 0);
            record.put("n_relationships_total", 0);
            record.put("by_type", Map.of());
            record.put("refactorings", List.of());
            record.put("same_relationships", List.of());
            record.put("near_misses", List.of());
            return record;
        }

        // RefDiff returns relationships in an unordered Set, so impose a stable
        // ordering here to keep the emitted JSON reproducible across runs.
        List<Relationship> sorted = new ArrayList<>(diff.getRelationships());
        sorted.sort(STABLE_ORDER);

        List<Map<String, Object>> refactorings = new ArrayList<>();
        List<Map<String, Object>> sameRelationships = new ArrayList<>();
        // by_type counts refactorings only (excludes SAME); SAME is reported via n_same.
        Map<String, Integer> byType = new TreeMap<>();
        int sameCount = 0;

        for (Relationship rel : sorted) {
            Map<String, Object> relMap = relationshipToMap(rel);
            if (rel.isRefactoring()) {
                byType.merge(rel.getType().name(), 1, Integer::sum);
                refactorings.add(relMap);
            } else {
                sameCount++;
                if (includeSame) {
                    sameRelationships.add(relMap);
                }
            }
        }

        record.put("n_refactorings", refactorings.size());
        record.put("n_same", sameCount);
        record.put("n_relationships_total", sorted.size());
        record.put("by_type", byType);
        record.put("refactorings", refactorings);
        record.put("same_relationships", sameRelationships);
        record.put(
            "near_misses",
            buildNearMisses(
                diff,
                discardedMatches != null ? discardedMatches : List.of(),
                nearMissBand));
        return record;
    }

    private static List<Map<String, Object>> buildNearMisses(
            CstDiff diff,
            List<CollectingMatcherMonitor.DiscardedMatch> discarded,
            NearMissScoreBand band) {
        Map<CstNode, CstNode> matched = new HashMap<>();
        for (Relationship rel : diff.getRelationships()) {
            CstNode before = rel.getNodeBefore();
            CstNode after = rel.getNodeAfter();
            if (before != null && after != null) {
                matched.put(before, after);
            }
        }

        Set<String> seen = new HashSet<>();
        List<Map<String, Object>> nearMisses = new ArrayList<>();
        for (CollectingMatcherMonitor.DiscardedMatch dm : discarded) {
            if (dm.score < band.min || dm.score >= band.max) {
                continue;
            }
            String dedupKey = nodeKey(dm.before) + "->" + nodeKey(dm.after);
            if (!seen.add(dedupKey)) {
                continue;
            }
            String inferredType = inferNearMissType(dm.before, dm.after, matched);
            if (inferredType == null) {
                continue;
            }
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("type", inferredType);
            entry.put("score", dm.score);
            entry.put("before", nodeOrNull(dm.before));
            entry.put("after", nodeOrNull(dm.after));
            nearMisses.add(entry);
        }
        nearMisses.sort(Comparator
            .comparing((Map<String, Object> m) -> (String) m.get("type"))
            .thenComparing(m -> nodeKeyFromMap((Map<String, Object>) m.get("before")))
            .thenComparing(m -> nodeKeyFromMap((Map<String, Object>) m.get("after")))
            .thenComparing(m -> (Double) m.get("score")));
        return nearMisses;
    }

    private static String nodeKeyFromMap(Map<String, Object> node) {
        if (node == null) {
            return "";
        }
        String file = String.valueOf(node.getOrDefault("file", ""));
        Object lineObj = node.get("line");
        int line = lineObj instanceof Number ? ((Number) lineObj).intValue() : 0;
        String localName = String.valueOf(node.getOrDefault("localName", ""));
        return file + ":" + line + ":" + localName;
    }

    /**
     * Mirrors RefDiff {@code findRelationshipForCandidate} for same-location pairs only.
     * Returns {@code null} for SAME, MOVE*, or unmatched parents.
     */
    private static String inferNearMissType(
            CstNode n1, CstNode n2, Map<CstNode, CstNode> matched) {
        if (!sameType(n1, n2)) {
            return null;
        }
        if (!sameLocation(n1, n2, matched)) {
            return null;
        }
        if (sameSignature(n1, n2)) {
            return null;
        }
        if (sameName(n1, n2)) {
            return RelationshipType.CHANGE_SIGNATURE.name();
        }
        return RelationshipType.RENAME.name();
    }

    private static boolean sameType(CstNode n1, CstNode n2) {
        if (n1.getType() == null || n2.getType() == null) {
            return false;
        }
        return n1.getType().equals(n2.getType());
    }

    private static boolean sameName(CstNode n1, CstNode n2) {
        String s1 = n1.getSimpleName();
        String s2 = n2.getSimpleName();
        return s1 != null && s1.equals(s2);
    }

    private static boolean sameSignature(CstNode n1, CstNode n2) {
        String l1 = n1.getLocalName();
        String l2 = n2.getLocalName();
        return l1 != null && l1.equals(l2);
    }

    private static boolean sameLocation(CstNode n1, CstNode n2, Map<CstNode, CstNode> matched) {
        if (!n1.getParent().isPresent() || !n2.getParent().isPresent()) {
            return false;
        }
        CstNode matchedParent = matched.get(n1.getParent().get());
        return matchedParent != null && matchedParent.equals(n2.getParent().get());
    }

    /**
     * Stable, content-based ordering for relationships so the JSON record is reproducible.
     * Orders by relationship type, then the before/after node location+name, then similarity.
     */
    private static final Comparator<Relationship> STABLE_ORDER = Comparator
        .comparing((Relationship r) -> r.getType().name())
        .thenComparing(r -> nodeKey(r.getNodeBefore()))
        .thenComparing(r -> nodeKey(r.getNodeAfter()))
        .thenComparing(r -> r.getSimilarity() == null ? -1.0 : r.getSimilarity());

    private static String nodeKey(CstNode node) {
        if (node == null) {
            return "";
        }
        Location loc = node.getLocation();
        String file = loc != null ? loc.getFile() : "";
        int line = loc != null ? loc.getLine() : 0;
        String localName = node.getLocalName() != null ? node.getLocalName() : "";
        return file + ":" + line + ":" + localName;
    }

    /**
     * Maps a single relationship to its JSON form.
     *
     * <p>Note: {@code similarity} is {@code null} for relationships matched by id/name/signature
     * (e.g. RENAME, MOVE, CHANGE_SIGNATURE, SAME). RefDiff only attaches a score to
     * EXTRACT, EXTRACT_MOVE and INLINE (set in {@code matchExtract}/{@code matchInline}).
     * When {@code similarity} is null, {@code description_with_score} is identical to
     * {@code description_standard}.
     */
    private static Map<String, Object> relationshipToMap(Relationship rel) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("type", rel.getType().name());
        map.put("similarity", rel.getSimilarity());
        map.put("description_standard", rel.getStandardDescription());
        map.put("description_with_score", descriptionWithScore(rel));
        map.put("before", nodeOrNull(rel.getNodeBefore()));
        map.put("after", nodeOrNull(rel.getNodeAfter()));
        return map;
    }

    private static String descriptionWithScore(Relationship rel) {
        String standard = rel.getStandardDescription();
        if (rel.getSimilarity() == null) {
            return standard;
        }
        String prefix = rel.getType().name() + "\t";
        String rest = standard.startsWith(prefix) ? standard.substring(prefix.length()) : standard;
        return rel.getType().name()
            + " (score="
            + String.format("%.3f", rel.getSimilarity())
            + ")\t"
            + rest;
    }

    private static Map<String, Object> nodeOrNull(CstNode node) {
        NodeSnapshot snap = NodeSnapshot.from(node);
        if (snap == null) {
            return null;
        }
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("kind", snap.kind);
        map.put("localName", snap.localName);
        map.put("file", snap.file);
        map.put("line", snap.line);
        map.put("path", snap.path);
        return map;
    }
}
