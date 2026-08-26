# -*- coding: utf-8 -*-
p = 'server/main.py'
s = open(p, encoding='utf-8').read()
old = '@app.get("/api/jobs/{job_id}")'
new = '''@app.post("/api/jobs/{job_id}/analyze")
def api_reanalyze(job_id: str):
    """重新分析(提示词升级后可用)。"""
    job = get_job(job_id) or _http404()
    job.set(status="analyzing", progress="重新分析中", error=None)
    run_in_background(job, stage_analyze)
    return {"ok": True}


@app.get("/api/jobs/{job_id}")'''
assert old in s, 'anchor 未匹配'
s = s.replace(old, new, 1)
open(p, 'w', encoding='utf-8').write(s)
print('reanalyze endpoint added')
