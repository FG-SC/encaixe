# Demo script — "rejected, learned why, evolved, matched"

About 8 minutes. Everything happens in the browser at <http://127.0.0.1:8000>; UI labels are quoted in Portuguese. The same story runs automatically in `tests/test_demo_story.py`.

## Before

```bash
.venv/Scripts/encaixe demo reset      # the scripted story runs on the seed world (68 fictional jobs)
.venv/Scripts/encaixe serve
```

With the real-jobs snapshot (`encaixe demo reset --snapshot demo`, 727 jobs) the story's step 8 does not work yet: Carla's job lands around position 180 of Ana's 395 eligible jobs, because its honest salary (R$ 8,000) ranks below the median that undisclosed salaries receive. Use that world to explore, not for the script.

Keep two files at hand: `app/seed/personas/ana.txt` (Ana's CV) and `app/seed/personas/lumen_ml_engineer_jr.txt` (Carla's job).

## 1. Ana arrives (candidate side)

1. Role **Candidato**, profile **"+ Novo perfil"**. Paste Ana's CV. Leave "Usar IA para ler meu CV" unticked (it is unticked by default); tick "Visível para recrutadores, anônimo até o encaixe".
2. **"Confira o que entendemos"**: every field says whether it was *declarado* (in her text) or *inferido* (e.g. Portuguese native). Experiences carry the skills used in each one: that is what "proven" means. Save.
3. **Raio-X**: what Encaixe understood, her star on the market map (the mean of the 10 most similar jobs — the rule is written under the map), how many open jobs are a good fit, the three skills that would unlock the most jobs, and the 4:5 share card with no personal data.

## 2. Open rules, before any swipe

4. **"Como o Encaixe decide"** (top bar): filters and thresholds, the formula, a worked example computed live by the engine.
5. **Vagas** → **"N vagas filtradas"**: "Sales Manager" is there, under *fora da sua área*, with the reason. Nothing disappears silently.
6. Open **"Por que estou vendo isto?"** on any card: raw value and position for each criterion, the pillar sums, and the note that position is relative while "bom encaixe" is a fixed rule.

## 3. Carla publishes (recruiter side)

7. Role **Recrutador**, profile **Carla Menezes · Lumen Dados**. **Vagas → "Publicar uma vaga"**: paste the ML Engineer Jr text. Review what was extracted (5 must requirements: Python, SQL, statistics, PyTorch, deep learning) and note the notice: *"Quem se candidatou verá o motivo da recusa e o que faltou."* Publish.

## 4. Ana applies, Carla declines with a reason

8. Back as Ana: find **ML Engineer Jr** in her deck (a platform job) and swipe right: an application (**Candidaturas** → *enviada*).
9. As Carla: **Candidatos** shows Ana's **blind** card first, badged *interessado(a)*. Try declining: a reason is mandatory for an applicant. Choose **skills**.

## 5. Ana learns why

10. As Ana: **Candidaturas** → *não avançou*, with the company's reason and: *"O que a vaga pede e seu perfil ainda não mostra: PyTorch, Deep learning. Com as duas, você comprovaria 5 de 5 obrigatórios e passaria a ser um bom encaixe para esta vaga."*

## 6. Time passes; Ana evolves

11. **Painel de dev** → advance the clock (e.g. 45 days).
12. As Ana: **Perfil** → add an experience dated this month using PyTorch and deep learning (e.g. *Analista de Dados (projeto de visão computacional)*). Save: it is a **relevant revision**.

## 7. The match

13. Ana's **Vagas**: ML Engineer Jr is back, badged *seu perfil mudou desde a recusa*, now a good fit. Swipe right: the application reopens as *enviada*.
14. As Carla: Ana is back, badged *perfil atualizado desde sua última avaliação*, 5 of 5 musts proven. Swipe right → **"É um encaixe!"** on both sides; Ana's contact appears under **Encaixes**.

## 8. If there is time: understanding, not just deciding

15. Ana's **Explorar**: which skill unlocks most jobs, where the jobs are, salaries of her good fits against her minimum, what her swipes reveal, her profile over time.
16. Carla's **Funil e Explorar**: the funnel, *qual requisito está esvaziando o funil* (the must whose removal adds most good fits), the candidate pool with k-anonymity, similar market jobs and their salaries.
