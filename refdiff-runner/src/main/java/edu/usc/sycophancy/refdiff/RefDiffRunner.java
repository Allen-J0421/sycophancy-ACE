package edu.usc.sycophancy.refdiff;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import org.eclipse.jgit.lib.ObjectId;
import org.eclipse.jgit.lib.Repository;
import org.eclipse.jgit.revwalk.RevCommit;
import org.eclipse.jgit.revwalk.RevWalk;
import org.eclipse.jgit.treewalk.TreeWalk;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectWriter;
import refdiff.core.diff.CstComparator;
import refdiff.core.diff.CstDiff;
import refdiff.core.diff.Relationship;
import refdiff.core.io.FilePathFilter;
import refdiff.core.io.GitHelper;
import refdiff.core.io.GitSourceTree;
import refdiff.core.io.SourceFile;
import refdiff.core.io.SourceFileSet;
import refdiff.parsers.LanguagePlugin;
import refdiff.parsers.java.JavaPlugin;
import refdiff.parsers.js.JsPlugin;

/**
 * CLI wrapper around RefDiff for local git repositories.
 */
public final class RefDiffRunner {

    private RefDiffRunner() {}

    public static void main(String[] args) {
        CliOptions opts;
        try {
            opts = CliOptions.parse(args);
        } catch (IllegalArgumentException e) {
            System.err.println(e.getMessage());
            printUsageAndExit(1);
            return;
        }

        File repoPath = new File(opts.repo).getAbsoluteFile();
        File gitDir;
        try {
            gitDir = resolveGitDir(repoPath);
        } catch (GitDirException e) {
            System.err.println(e.getMessage());
            System.exit(2);
            return;
        }

        String parentSha = "";
        String resolvedCommitSha = opts.commit;
        long startMs = System.currentTimeMillis();
        Map<String, Object> record;
        int exitCode = 0;

        try {
            File tempDir = new File(".refdiff-tmp").getAbsoluteFile();
            if (!tempDir.exists() && !tempDir.mkdirs()) {
                throw new RuntimeException("Failed to create temp directory: " + tempDir);
            }

            CollectingMatcherMonitor monitor = new CollectingMatcherMonitor();
            DiffResult diffResult;
            if ("js".equals(opts.lang)) {
                try (JsPlugin plugin = new JsPlugin()) {
                    diffResult = runDiff(gitDir, opts.commit, plugin, monitor);
                }
            } else {
                JavaPlugin plugin = new JavaPlugin(tempDir);
                diffResult = runDiff(gitDir, opts.commit, plugin, monitor);
            }

            resolvedCommitSha = diffResult.commitSha;
            parentSha = diffResult.parentSha != null ? diffResult.parentSha : "";

            if (opts.matcherLog != null) {
                File matcherFile = new File(opts.matcherLog);
                matcherFile.getParentFile().mkdirs();
                Files.write(matcherFile.toPath(), monitor.getLines(), StandardCharsets.UTF_8);
            }

            record = RefDiffExporter.buildRecord(
                repoPath.getPath(),
                resolvedCommitSha,
                parentSha,
                diffResult.diff,
                opts.includeSame,
                monitor.getLines(),
                diffResult.durationMs,
                true,
                "");
            record.put("language", opts.lang);

            if (!opts.quiet) {
                printHumanSummary(repoPath, gitDir, resolvedCommitSha, diffResult.diff);
            }

            writeOutput(record, opts);

        } catch (Exception e) {
            long durationMs = System.currentTimeMillis() - startMs;
            exitCode = 1;
            record = RefDiffExporter.buildRecord(
                repoPath.getPath(),
                resolvedCommitSha,
                parentSha,
                null,
                opts.includeSame,
                List.of(),
                durationMs,
                false,
                e.getMessage() != null ? e.getMessage() : e.getClass().getSimpleName());
            record.put("language", opts.lang);

            if (!opts.quiet) {
                System.err.println("RefDiff failed: " + e.getMessage());
            }

            try {
                writeOutput(record, opts);
            } catch (Exception writeErr) {
                System.err.println("Failed to write output: " + writeErr.getMessage());
                exitCode = 2;
            }
        }

        System.exit(exitCode);
    }

    private static DiffResult runDiff(
            File gitDir,
            String commit,
            LanguagePlugin plugin,
            CollectingMatcherMonitor monitor) throws Exception {
        FilePathFilter fileFilter = plugin.getAllowedFilesFilter();
        try (Repository repository = GitHelper.openRepository(gitDir)) {
            try (RevWalk rw = new RevWalk(repository)) {
                ObjectId objectId = repository.resolve(commit);
                if (objectId == null) {
                    throw new IllegalArgumentException("Unknown commit: " + commit);
                }
                RevCommit revCommit = rw.parseCommit(objectId);
                String sha = revCommit.getId().getName();

                RevCommit parentCommit = null;
                String parentSha = null;
                if (revCommit.getParentCount() >= 1) {
                    parentCommit = rw.parseCommit(revCommit.getParent(0).getId());
                    parentSha = parentCommit.getId().getName();
                }

                // Compare the FULL source tree at each commit (not just the files
                // changed in the commit). RefDiff's commit helper only returns
                // changed files, which makes nodes in untouched files vanish from
                // the snapshot and produces phantom delete/re-add signals. Feeding
                // the complete tree lets unchanged nodes match as SAME so every
                // turn carries a faithful full-repo node set.
                List<SourceFile> afterFiles = listSourceFiles(repository, revCommit, fileFilter);
                List<SourceFile> beforeFiles = parentCommit != null
                    ? listSourceFiles(repository, parentCommit, fileFilter)
                    : new ArrayList<>();

                ObjectId beforeId = parentCommit != null ? parentCommit.getId() : revCommit.getId();
                SourceFileSet before = new GitSourceTree(repository, beforeId, beforeFiles);
                SourceFileSet after = new GitSourceTree(repository, revCommit.getId(), afterFiles);

                CstComparator comparator = new CstComparator(plugin);
                long compareStartMs = System.currentTimeMillis();
                CstDiff diff = comparator.compare(before, after, monitor);
                long durationMs = System.currentTimeMillis() - compareStartMs;
                return new DiffResult(sha, parentSha, diff, durationMs);
            }
        }
    }

    /** Enumerate every source file in a commit's tree that passes the language filter. */
    private static List<SourceFile> listSourceFiles(
            Repository repository,
            RevCommit commit,
            FilePathFilter filter) throws Exception {
        List<SourceFile> files = new ArrayList<>();
        try (TreeWalk tw = new TreeWalk(repository)) {
            tw.addTree(commit.getTree());
            tw.setRecursive(true);
            while (tw.next()) {
                String path = tw.getPathString();
                if (filter.isAllowed(path)) {
                    files.add(new SourceFile(Paths.get(path)));
                }
            }
        }
        return files;
    }

    private static void writeOutput(Map<String, Object> record, CliOptions opts) throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        ObjectWriter writer = opts.pretty
            ? mapper.writerWithDefaultPrettyPrinter()
            : mapper.writer();
        if (opts.out != null) {
            try (OutputStream os = new FileOutputStream(opts.out)) {
                writer.writeValue(os, record);
            }
        } else {
            writer.writeValue(System.out, record);
        }
    }

    private static void printHumanSummary(File repoPath, File gitDir, String commitSha, CstDiff diff) {
        System.out.println("Repository: " + repoPath);
        System.out.println("Git dir:    " + gitDir);
        System.out.println("Commit:     " + commitSha);
        System.out.println();
        int count = 0;
        for (Relationship rel : diff.getRefactoringRelationships()) {
            System.out.println(rel.getStandardDescription());
            count++;
        }
        if (count == 0) {
            System.out.println("(no refactorings detected)");
        }
    }

    static CommitInfo resolveCommit(Repository repository, String commitRef) throws Exception {
        try (RevWalk rw = new RevWalk(repository)) {
            ObjectId objectId = repository.resolve(commitRef);
            if (objectId == null) {
                throw new IllegalArgumentException("Unknown commit: " + commitRef);
            }
            RevCommit commit = rw.parseCommit(objectId);
            String sha = commit.getId().getName();
            String parentSha = null;
            if (commit.getParentCount() >= 1) {
                parentSha = commit.getParent(0).getName();
            }
            return new CommitInfo(sha, parentSha);
        }
    }

    static final class CommitInfo {
        final String sha;
        final String parentSha;

        CommitInfo(String sha, String parentSha) {
            this.sha = sha;
            this.parentSha = parentSha;
        }
    }

    static final class DiffResult {
        final String commitSha;
        final String parentSha;
        final CstDiff diff;
        final long durationMs;

        DiffResult(String commitSha, String parentSha, CstDiff diff, long durationMs) {
            this.commitSha = commitSha;
            this.parentSha = parentSha;
            this.diff = diff;
            this.durationMs = durationMs;
        }
    }

    static File resolveGitDir(File path) throws GitDirException {
        File dotGit = new File(path, ".git");
        if (dotGit.isDirectory()) {
            return dotGit.getAbsoluteFile();
        }
        if (".git".equals(path.getName()) && path.isDirectory()) {
            return path.getAbsoluteFile();
        }
        if (path.isDirectory() && path.getName().endsWith(".git")) {
            return path.getAbsoluteFile();
        }
        throw new GitDirException("Not a git repository: " + path);
    }

    static final class GitDirException extends Exception {
        GitDirException(String message) {
            super(message);
        }
    }

    private static void printUsageAndExit(int code) {
        System.err.println("Usage: refdiff-runner --repo <path> --commit <sha> --lang java|js [--out <file.json>]");
        System.err.println("       [--include-same] [--matcher-log <file>] [--pretty] [--quiet]");
        System.exit(code);
    }

    static final class CliOptions {
        final String repo;
        final String commit;
        final String lang;
        final String out;
        final String matcherLog;
        final boolean includeSame;
        final boolean pretty;
        final boolean quiet;

        CliOptions(
                String repo,
                String commit,
                String lang,
                String out,
                String matcherLog,
                boolean includeSame,
                boolean pretty,
                boolean quiet) {
            this.repo = repo;
            this.commit = commit;
            this.lang = lang;
            this.out = out;
            this.matcherLog = matcherLog;
            this.includeSame = includeSame;
            this.pretty = pretty;
            this.quiet = quiet;
        }

        static CliOptions parse(String[] args) {
            String repo = null;
            String commit = null;
            String lang = null;
            String out = null;
            String matcherLog = null;
            boolean includeSame = false;
            boolean pretty = false;
            boolean quiet = false;

            for (int i = 0; i < args.length; i++) {
                String arg = args[i];
                switch (arg) {
                    case "--repo":
                        repo = requireValue(args, ++i, "--repo");
                        break;
                    case "--commit":
                        commit = requireValue(args, ++i, "--commit");
                        break;
                    case "--lang":
                        lang = requireValue(args, ++i, "--lang");
                        break;
                    case "--out":
                        out = requireValue(args, ++i, "--out");
                        break;
                    case "--matcher-log":
                        matcherLog = requireValue(args, ++i, "--matcher-log");
                        break;
                    case "--include-same":
                        includeSame = true;
                        break;
                    case "--pretty":
                        pretty = true;
                        break;
                    case "--quiet":
                        quiet = true;
                        break;
                    default:
                        throw new IllegalArgumentException("Unknown argument: " + arg);
                }
            }

            if (repo == null || commit == null) {
                throw new IllegalArgumentException("--repo and --commit are required");
            }
            if (lang == null) {
                throw new IllegalArgumentException("--lang is required (java or js)");
            }
            if (!"java".equals(lang) && !"js".equals(lang)) {
                throw new IllegalArgumentException("--lang must be java or js");
            }
            return new CliOptions(repo, commit, lang, out, matcherLog, includeSame, pretty, quiet);
        }

        private static String requireValue(String[] args, int index, String flag) {
            if (index >= args.length) {
                throw new IllegalArgumentException("Missing value for " + flag);
            }
            return args[index];
        }
    }
}
