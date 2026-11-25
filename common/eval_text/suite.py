"""NEXI text eval suite v1: 12 tasks, deterministic scoring, no vibes.

Categories: coding (execution-verified), math/reasoning (exact answer),
format/instruction (parse-checked), knowledge (exact).

Each task: {"id", "cat", "prompt", "check": spec}
check kinds:
  exec:test_code  - model must output python defining the requested function;
                    we extract the code block, exec it, run test_code asserts
  exact:value     - normalized answer string must appear in output
  json:schema     - output must parse as json containing required keys
  bullets:n       - exactly n bullet lines
"""
TASKS = [
    {"id": "code-fib", "cat": "coding",
     "prompt": "Write a Python function `fib(n)` returning the nth Fibonacci number (fib(0)=0, fib(1)=1). Output ONLY a python code block.",
     "check": {"kind": "exec", "test": "assert fib(0)==0 and fib(1)==1 and fib(10)==55 and fib(20)==6765"}},
    {"id": "code-revwords", "cat": "coding",
     "prompt": "Write a Python function `rev_words(s)` that reverses the order of words in a string, collapsing whitespace. Example: 'the  sky is' -> 'is sky the'. Output ONLY a python code block.",
     "check": {"kind": "exec", "test": "assert rev_words('the  sky is')=='is sky the' and rev_words('a')=='a' and rev_words('')==''"}},
    {"id": "code-twosum", "cat": "coding",
     "prompt": "Write a Python function `two_sum(nums, target)` returning indices of the two numbers that add to target, as a tuple. Output ONLY a python code block.",
     "check": {"kind": "exec", "test": "assert two_sum([2,7,11,15],9)==(0,1) and two_sum([3,2,4],6)==(1,2)"}},
    {"id": "code-csv", "cat": "coding",
     "prompt": "Write a Python function `max_value(csv_text)` that parses CSV text with a header row and returns the maximum numeric value in the 'value' column. Output ONLY a python code block.",
     "check": {"kind": "exec", "test": "assert max_value('name,value\\na,3\\nb,7\\nc,5')==7.0 and max_value('x,value\\nq,-2')==-2.0"}},
    {"id": "math-gsm", "cat": "math",
     "prompt": "A train travels 120 km in 1.5 hours, then 80 km in 0.5 hours. What is its average speed for the whole trip in km/h? Answer with just the number.",
     "check": {"kind": "exact", "value": "100"}},
    {"id": "math-logic", "cat": "math",
     "prompt": "Alice is older than Bob. Bob is older than Carol. Dave is younger than Carol. Who is the youngest? Answer with just the name.",
     "check": {"kind": "exact", "value": "dave"}},
    {"id": "math-pct", "cat": "math",
     "prompt": "A shirt costs $45 after a 25% discount. What was the original price in dollars? Answer with just the number.",
     "check": {"kind": "exact", "value": "60"}},
    {"id": "fmt-json", "cat": "format",
     "prompt": 'Output a JSON object with keys "city", "country", "population_m" for Tokyo. Output ONLY valid JSON, no markdown fences.',
     "check": {"kind": "json", "keys": ["city", "country", "population_m"]}},
    {"id": "fmt-bullets", "cat": "format",
     "prompt": "List exactly 3 colors as bullet points (lines starting with '- '). No other text.",
     "check": {"kind": "bullets", "n": 3}},
    {"id": "fmt-toolcall", "cat": "format",
     "prompt": 'Format a tool call for function get_weather(city, units) with city="Paris", units="metric" as a JSON object with keys "name" and "arguments". Output ONLY valid JSON.',
     "check": {"kind": "json", "keys": ["name", "arguments"]}},
    {"id": "know-capital", "cat": "knowledge",
     "prompt": "What is the capital of Australia? Answer with just the city name.",
     "check": {"kind": "exact", "value": "canberra"}},
    {"id": "know-physics", "cat": "knowledge",
     "prompt": "What particle carries the electromagnetic force? Answer with just the particle name.",
     "check": {"kind": "exact", "value": "photon"}},
]
