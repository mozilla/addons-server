// vim:se ft=javascript sts=2 sw=2 et:
"use strict";

function deepEqual(left, right) {
  if (left === right)
    return true;

  if (!(left && right &&
        typeof left == "object" &&
        typeof right == "object"))
    return false;

  if (Object.getPrototypeOf(left) !== Object.getPrototypeOf(right))
    return false;

  let allKeys = obj => new Set([...Object.getOwnPropertyNames(obj),
                                ...Object.getOwnPropertySymbols(obj)]);

  let leftKeys = allKeys(left);
  let rightKeys = allKeys(right);

  if (leftKeys.size != rightKeys.size)
    return false;

  for (let key of leftKeys) {
    if (!rightKeys.has(key))
      return false;

    if (!deepEqual(left[key], right[key]))
      return false
  }

  return true;
}

function mungeFile(text) {
  let lines = [];

  let match;
  let expr = /[^\r\n]*\r?\n?/g;
  while ((match = expr.exec(text)) && match[0])
    lines.push(match[0]);


  let ast = Reflect.parse(text);
  if (ast.type != "Program")
    throw new SyntaxError;


  const REPLACEMENTS = {
    "let": "var",
    "const": "var  ",
  };

  let changes = 0;
  for (let node of ast.body) {
    if (!(node.type == "VariableDeclaration" &&
          node.kind in REPLACEMENTS))
      continue;

    let kind = node.kind;
    let start = node.loc.start;
    let lineNo = start.line - 1;

    if (lineNo >= lines.length)
      continue;

    let line = lines[lineNo];
    if (line.substr(start.column, kind.length) != kind)
      continue;

    line = [line.slice(0, start.column),
            REPLACEMENTS[kind],
            line.slice(start.column + kind.length)].join("");

    lines[lineNo] = line;
    node.kind = "var";
    changes++;
  }

  if (!changes)
    return;

  let newText = lines.join("");
  let newAST = Reflect.parse(newText);

  if (deepEqual(ast, newAST))
    return newText;
}

for (let file of scriptArgs) {
  let input = os.file.readFile(file, "binary");

  // Convert to a string, ignoring encoding.
  //
  // The file may not be valid UTF-8, so treating it as a single-byte
  // encoding leaves the least chance of errors during re-encoding.
  // Since we'll only be changing `var` and `const` keywords, and only
  // if the file parses, the chance of causing breakage this way is
  // vanishingly small.
  input = String.fromCharCode.apply(null, input);

  try {
    let result = mungeFile(input);
    if (result !== undefined) {
      let array = Uint8Array.from(result, c => c.charCodeAt(0));
      os.file.writeTypedArrayToFile(file, array);
    }
  } catch (e if e instanceof SyntaxError) {
    console.log("SyntaxeError: ", e);
  }
}
