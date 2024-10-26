import os
import ai
import json
import log
from collections import deque

llm = ai.LLM()

SYSTEM_PROMPT_PARSE_REFS = """
你是一个 Oracle 存储过程开发的专家，下面我会给你一段 Oracle 存储过程的代码，请帮我分析这段代码，要求：
1. 找到所有对于外部包的调用（不在本包中定义的包， 也不包括 Oracle 的系统包) 
2. 在本包中定义的包名，并按照格式输出 (使用 JSON 格式的列表)：
{
  "deps": [
     "{package_name}.{function_name}"
     ...
  ],
  "package_name": ["{package_name}", ...]
}

<code>%s</code>
"""


SYSTEM_PROMPT_PROCESS_FILE = """
你是一个 JAVA 专家和 MySQL 专家，正在将 Oracle 的存储过程改写成 JAVA 的等价程序
上面是一段 ORACLE 的存储过程，请转换成 JAVA 的等价程序：

1. 涉及到查询和更新数据库的部分，使用 MySQL JDBC 的 API 实现，使用 SQL，但是不允许使用 PL/SQL。
2. 我会给出在外部定义的已有函数的符号表（在Oracle中的定义，以及 Java的类名和函数签名），如果遇到外部定义的函数，请直接使用。
3. 生产Java 代码, 注释中标注来自哪个Oracle的包和函数签名, 给出完整实现，不要省略，并统计所有转换过的所有的函数签名（Oracle 和 Java 的分别都输出），包括参数和返回值，使用json, 格式如下：
{ 
"java_code": "{generated_java_code}",
"symbols": [{"oracle": "{packagename_in_oracle}.{functionname_in_oracle}(PARAM1TYPE PARAM1NAME, PARAM2TYPE PARAM2NAME, ...) RETURNS RETURNTYPE", "java": "ClassName.FunctionName(PARAM1TYPE PARAM1NAME, PARAM2TYPE PARAM2NAME, ...) RETURNS RETURNTYPE"},...]
}

<predefined_symbols>
%s
</predefined_symbols>

<stored_procedure>
%s
</stored_procedure>
"""

def parse_refs(code: str) -> dict:
    resp = llm.ask([{"role": "system", "content": SYSTEM_PROMPT_PARSE_REFS % code}],
                   json_mode=True, cached_mode=True)
    json_content = resp["content"]
    return json.loads(json_content)

def generate_java_code(code: str, predefined_symbols: set) -> tuple[str, list[dict]]:
    str_symbols = "\n".join(predefined_symbols)
    resp = llm.ask([{"role": "system", "content": SYSTEM_PROMPT_PROCESS_FILE % (str_symbols, code)}],
                   json_mode=True, cached_mode=True)
    json_content = resp["content"]
    obj =  json.loads(json_content)
    return obj["java_code"], obj["symbols"]

def scan_sql_files(directory: str) -> list[str]:
    sql_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.sql'):
                sql_files.append(os.path.join(root, file))
    return sql_files

class Processor:
    def __init__(self, working_dir: str):
        self.working_dir = working_dir
        self.progress_file = os.path.join(working_dir, ".progress.json")

        self.file_dep_graph = {}
        self.processed_files = set()
        self.symbols = set()

        if os.path.exists(self.progress_file):
            self.load_progress()

        # Build the file dependency graph if not built
        if len(self.file_dep_graph) == 0:
            self.file_dep_graph = self.build_callgraph()

    def build_callgraph(self) -> dict:
        sql_files = scan_sql_files(self.working_dir)
        package_2_file = {}
        file_dep_graph = {}
        file_contents = {}
        file_refs = {}

        # Read all files and store their contents and parse_refs results
        for sql_file in sql_files:
            with open(sql_file, 'r', encoding='utf-8') as f:
                code = f.read()
                file_contents[sql_file] = code
                file_refs[sql_file] = parse_refs(code)

        # Create a mapping from package name to file
        for sql_file, refs in file_refs.items():
            package_names = refs.get("package_name", [])
            for package_name in package_names:
                filename = os.path.basename(sql_file)
                package_2_file[package_name] = filename

        # Build the file dependency graph
        for sql_file, refs in file_refs.items():
            filename = os.path.basename(sql_file)
            dependencies = refs.get("deps", [])
            dependent_files = set()
            for dep in dependencies:
                package_name = dep.split('.')[0]
                if package_name in package_2_file:
                    dep_filename = package_2_file[package_name]
                    if dep_filename != filename:
                        dependent_files.add(dep_filename)
            file_dep_graph[filename] = dependent_files
        # turn all set to list
        for filename, deps in file_dep_graph.items():
            file_dep_graph[filename] = list(deps)
        return file_dep_graph

    def load_progress(self):
        if os.path.exists(self.progress_file):
            with open(self.progress_file, 'r') as f:
                data = json.load(f)
                self.processed_files = set(data.get("processed_files", []))
                self.symbols = set(data.get("symbols", []))
                self.file_dep_graph = data.get("file_dep_graph", {})
        else:
            self.processed_files = set()
            self.symbols = set()
            self.file_dep_graph = {}

    def save_progress(self):
        with open(self.progress_file, 'w') as f:
            data = json.dumps({
                "processed_files": list(self.processed_files),
                "symbols": list(self.symbols),
                "file_dep_graph": self.file_dep_graph,
            })
            f.write(data)

    def process_file(self, filename: str):
        if filename in self.processed_files:
            log.info(f"Skip {filename} because it has been processed")
            return
        for dep in self.file_dep_graph.get(filename, []):
            self.process_file(dep)
        log.info(f"Processing {filename}")
        with open(os.path.join(self.working_dir, filename), 'r', encoding='utf-8') as f:
            code = f.read()
            generated_code, new_symbols = generate_java_code(code, self.symbols)
            print(f"Generated code for {filename}")
            print("---")
            # TODO: Write to file
            print(generated_code)
            print("---")
            for symbol in new_symbols:
                key = f"{symbol['oracle']} -> {symbol['java']}"
                self.symbols.add(key)
            self.processed_files.add(filename)
            self.save_progress()

    def process(self):
        for file in self.file_dep_graph:
            self.process_file(file)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--working-dir", type=str, required=True)
    args = parser.parse_args()

    processor = Processor(args.working_dir)
    processor.process()
