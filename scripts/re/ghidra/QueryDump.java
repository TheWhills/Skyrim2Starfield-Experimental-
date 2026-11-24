// Answer a batch of read-only questions about the open program and write the answers to a text file.
// Run headless (see scripts/re/ghidra_query.py), arguments: <command file> <output file>.
// Commands, one per line ('#' starts a comment):
//   info                      program name, MD5 of the imported file, image base, function count
//   decomp <addr>             decompile the function containing <addr>
//   xrefs <addr>              references to <addr>, with the function each one is in
//   callers <addr>            functions that call the function containing <addr>
//   qwords <addr> <n>         n pointer-sized values from <addr>, each with its symbol / string if any
//   string <addr>             the string at <addr>
//   sym <regex>               symbols whose name matches <regex> (max 200)
//   vtable <class>            addresses of the RTTI vftable symbols for <class> and their first 64 slots
//   find <ascii>              addresses of an ASCII string in initialised memory (max 50) and their xrefs
//   insn <start> <end> <regex>  instructions in [start, end] whose text matches <regex> (max 400)
// @category S2S
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.regex.Pattern;

import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.*;

public class QueryDump extends GhidraScript {
    private PrintWriter out;
    private DecompInterface dec;

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        List<String> lines = Files.readAllLines(Paths.get(args[0]), StandardCharsets.UTF_8);
        out = new PrintWriter(new OutputStreamWriter(new FileOutputStream(args[1]), StandardCharsets.UTF_8));
        dec = new DecompInterface();
        dec.openProgram(currentProgram);
        try {
            for (String raw : lines) {
                String line = raw.trim();
                if (line.isEmpty() || line.startsWith("#")) continue;
                out.println("==== " + line);
                try {
                    handle(line);
                } catch (Exception e) {
                    out.println("ERROR " + e);
                }
                out.flush();
            }
        } finally {
            dec.dispose();
            out.close();
        }
    }

    private Address addr(String s) {
        return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(Long.parseUnsignedLong(
            s.toLowerCase().replace("0x", ""), 16));
    }

    private String describe(Address a) {
        StringBuilder sb = new StringBuilder(a.toString());
        Symbol s = getSymbolAt(a);
        if (s != null) sb.append(" <").append(s.getName(true)).append(">");
        Function f = getFunctionContaining(a);
        if (f != null && (s == null || !f.getEntryPoint().equals(a)))
            sb.append(" in ").append(f.getName()).append("@").append(f.getEntryPoint());
        Data d = getDataAt(a);
        if (d != null && d.hasStringValue()) sb.append(" \"").append(d.getDefaultValueRepresentation()).append("\"");
        return sb.toString();
    }

    private void handle(String line) throws Exception {
        String[] p = line.split("\\s+", 3);
        switch (p[0]) {
            case "info": {
                out.println("name " + currentProgram.getName());
                out.println("md5 " + currentProgram.getExecutableMD5());
                out.println("path " + currentProgram.getExecutablePath());
                out.println("base " + currentProgram.getImageBase());
                out.println("functions " + currentProgram.getFunctionManager().getFunctionCount());
                break;
            }
            case "decomp": {
                Function f = getFunctionContaining(addr(p[1]));
                if (f == null) { out.println("no function"); break; }
                DecompileResults r = dec.decompileFunction(f, 120, monitor);
                if (!r.decompileCompleted()) { out.println("failed: " + r.getErrorMessage()); break; }
                out.println(r.getDecompiledFunction().getC());
                break;
            }
            case "xrefs": {
                int n = 0;
                for (Reference r : getReferencesTo(addr(p[1]))) {
                    out.println(r.getReferenceType() + " from " + describe(r.getFromAddress()));
                    if (++n >= 300) { out.println("..."); break; }
                }
                break;
            }
            case "callers": {
                Function f = getFunctionContaining(addr(p[1]));
                if (f == null) { out.println("no function"); break; }
                for (Function c : f.getCallingFunctions(monitor)) out.println(c.getName() + "@" + c.getEntryPoint());
                for (Reference r : getReferencesTo(f.getEntryPoint()))
                    if (!r.getReferenceType().isCall()) out.println("ref " + r.getReferenceType() + " from " + describe(r.getFromAddress()));
                break;
            }
            case "qwords": {
                Address a = addr(p[1]);
                int n = Integer.parseInt(p[2]);
                Memory m = currentProgram.getMemory();
                for (int i = 0; i < n; i++) {
                    Address at = a.add(8L * i);
                    long v = m.getLong(at);
                    String d = "";
                    try {
                        Address t = addr(Long.toHexString(v));
                        if (m.contains(t)) d = " -> " + describe(t);
                    } catch (Exception e) { /* not an address */ }
                    out.println(at + ": " + String.format("%016x", v) + d);
                }
                break;
            }
            case "string": {
                Address a = addr(p[1]);
                StringBuilder sb = new StringBuilder();
                Memory m = currentProgram.getMemory();
                for (int i = 0; i < 512; i++) {
                    byte b = m.getByte(a.add(i));
                    if (b == 0) break;
                    sb.append((char) (b & 0xff));
                }
                out.println(sb);
                break;
            }
            case "sym": {
                Pattern re = Pattern.compile(line.substring(4).trim());
                int n = 0;
                SymbolIterator it = currentProgram.getSymbolTable().getAllSymbols(true);
                while (it.hasNext() && n < 200) {
                    Symbol s = it.next();
                    String name = s.getName(true);
                    if (re.matcher(name).find()) { out.println(s.getAddress() + " " + name); n++; }
                }
                break;
            }
            case "vtable": {
                String cls = p[1];
                SymbolIterator it = currentProgram.getSymbolTable().getAllSymbols(true);
                while (it.hasNext()) {
                    Symbol s = it.next();
                    String name = s.getName(true);
                    if (name.equals(cls + "::vftable") || name.equals(cls + "::`vftable'")) {
                        out.println("vftable " + s.getAddress());
                        handle("qwords " + s.getAddress() + " 64");
                    }
                }
                break;
            }
            case "find": {
                byte[] needle = line.substring(5).getBytes(StandardCharsets.US_ASCII);
                Memory m = currentProgram.getMemory();
                Address start = currentProgram.getMinAddress();
                int n = 0;
                while (n < 50) {
                    Address hit = m.findBytes(start, needle, null, true, monitor);
                    if (hit == null) break;
                    out.println("at " + hit);
                    for (Reference r : getReferencesTo(hit)) out.println("  " + r.getReferenceType() + " from " + describe(r.getFromAddress()));
                    start = hit.add(1);
                    n++;
                }
                break;
            }
            case "insn": {
                String[] q = line.split("\\s+", 4);
                Pattern re = Pattern.compile(q[3]);
                AddressSet range = new AddressSet(addr(q[1]), addr(q[2]));
                InstructionIterator it = currentProgram.getListing().getInstructions(range, true);
                int n = 0;
                while (it.hasNext() && n < 400) {
                    Instruction ins = it.next();
                    String text = ins.toString();
                    if (re.matcher(text).find()) { out.println(describe(ins.getAddress()) + "  " + text); n++; }
                }
                break;
            }
            default:
                out.println("unknown command");
        }
    }
}
