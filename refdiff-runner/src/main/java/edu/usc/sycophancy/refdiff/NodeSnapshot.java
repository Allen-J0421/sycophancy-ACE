package edu.usc.sycophancy.refdiff;

import java.util.List;

import refdiff.core.cst.CstNode;
import refdiff.core.cst.Location;
import refdiff.core.diff.CstRootHelper;

/**
 * JSON-friendly snapshot of a CST node.
 */
public final class NodeSnapshot {

    public final int id;
    public final String kind;
    public final String localName;
    public final String file;
    public final int line;
    public final List<String> path;

    public NodeSnapshot(int id, String kind, String localName, String file, int line, List<String> path) {
        this.id = id;
        this.kind = kind;
        this.localName = localName;
        this.file = file;
        this.line = line;
        this.path = path;
    }

    public static NodeSnapshot from(CstNode node) {
        if (node == null) {
            return null;
        }
        Location loc = node.getLocation();
        String file = loc != null ? loc.getFile() : "";
        int line = loc != null ? loc.getLine() : 0;
        String kind = node.getType() != null ? node.getType().replace("Declaration", "") : "";
        return new NodeSnapshot(
            node.getId(),
            kind,
            node.getLocalName(),
            file,
            line,
            CstRootHelper.getNodePath(node));
    }
}
