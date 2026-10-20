# Como o Encaixe decide

> Esta página é gerada automaticamente a partir de `app/config.py`, a mesma configuração que o ranking usa.
> Não existe regra escondida: se um número muda lá, muda aqui. Versão das regras: `3b729c7c92dc`.

O Encaixe ordena vagas para candidatos (lado C) e candidatos para vagas (lado B) com o **mesmo procedimento**.
Ele não usa pesos escolhidos à mão: cada item é ordenado em cada critério, as posições são somadas e a lista sai
ordenada pela soma — a lógica da "fórmula mágica" de Joel Greenblatt.

## 1. Filtros: o que não é negociável

Antes de ordenar, cada vaga passa por filtros. Uma vaga filtrada **não some em silêncio**: ela aparece em
"Vagas que não te mostramos", com o motivo e o limite que não passou.

| Filtro | Quando exclui |
|---|---|
| Vaga fechada | a vaga não está mais aberta (lado C) |
| Perfil não visível | o candidato escolheu não aparecer para recrutadores (lado B) |
| Modalidade não aceita | a vaga é remota, híbrida ou presencial e você não marcou essa modalidade |
| Fora da distância | vaga presencial ou híbrida a mais de `max_distance_km` da sua cidade (distância em linha reta entre as cidades) |
| Elegibilidade de país | a vaga aceita apenas pessoas de certos países e o seu não está entre eles |
| Salário abaixo do mínimo | o teto da vaga fica abaixo de **70%** do seu salário mínimo (quando os dois são conhecidos) |
| Senioridade distante | a distância na escada de senioridade é de **3 ou mais** níveis |
| Fora da área | você não comprova nenhum requisito obrigatório da vaga **e** não tem nenhum domínio da taxonomia em comum com ela |

A escada de senioridade é: L1 Estágio · L2 Júnior · L3 Pleno · L4 Sênior · L5 Staff · L6 Principal.
O título do cargo manda; anos de experiência servem só quando o título não diz o nível.

**Por que "fora da área" é filtro e não critério:** a soma de posições compensa um critério ruim com outro bom.
Uma vaga de vendas com ótimo salário poderia subir para o meio da lista de um perfil de dados. O que não é
negociável tem de ser filtro. O domínio da vaga é o da maioria das skills dela; os seus são os das skills que
você comprova. Skills transversais (Excel, Git, negociação, gestão de projetos…) não definem área.

## 2. Critérios e pilares

| Pilar | Pergunta | Critério | O que é medido | Melhor |
|---|---|---|---|---|
| **Atende** | Você atende ao que a vaga pede? | Requisitos | ver abaixo (ordem lexicográfica) | maior |
| **Atende** | Você atende ao que a vaga pede? | Aderência semântica | cosseno entre a vaga e o seu perfil (modelo de embeddings multilíngue) | maior |
| **Atende** | Você atende ao que a vaga pede? | Aderência de cargo | cosseno entre o título da vaga e a média dos títulos das suas experiências | maior |
| **Atende** | Você atende ao que a vaga pede? | Senioridade | distância na escada de senioridade | menor |
| **Interessa** | A vaga oferece o que você quer? | Salário | folga = (teto da vaga − seu mínimo) / seu mínimo, com câmbio aproximado | maior |
| **Interessa** | A vaga oferece o que você quer? | Modalidade e distância | 0 se a vaga é remota (e você aceita) ou na mesma cidade; senão, a distância em km | menor |
| **Interessa** | A vaga oferece o que você quer? | Fuso | horas de sobreposição do expediente 9h–18h (só vagas remotas) | maior |
| **Histórico** | Parece com o que você curtiu? | Histórico | parecença com o que você curtiu e recusou (só no feedback-v1) | maior |


### Requisitos, em ordem lexicográfica

O critério Requisitos compara uma chave depois da outra (só passa para a próxima em caso de empate):

1. % dos obrigatórios **comprovados** — skill usada numa experiência com datas;
2. % dos obrigatórios comprovados **nos últimos 3 anos**;
3. % dos obrigatórios só **listados** — no perfil, sem experiência com datas;
4. % dos desejáveis comprovados.

Uma skill "pai" ou "filha" na taxonomia (ex.: PyTorch → deep learning → machine learning) vale
**0,5** requisito. Idiomas exigidos pela vaga contam como requisitos obrigatórios.
**Por que lexicográfico:** comprovar vem sempre antes de listar, e a recência só desempata. Encher o currículo de
palavras-chave não funciona: skill listada, mesmo repetida, nunca supera skill comprovada.

## 3. Da posição à ordem

1. **Posição por critério.** Em cada critério, cada item recebe uma posição (1 = melhor).
   - **Empate:** valores dentro da precisão publicada contam como empate e recebem a posição média.
     Precisões: cosseno 0,02; salário 5%; distância 5 km; fuso 1 h; histórico 0,02.
   - **Desconhecido** (por exemplo, vaga sem salário) recebe o valor mediano daquele critério e aparece como
     "não informado". O fuso só se aplica a vagas remotas; nas outras ele fica neutro ("não se aplica").
   - **Efeito colateral, dito com todas as letras:** no critério salário, a vaga que informa salário bom sobe, a que
     informa salário ruim desce, e a que não informa fica no meio. Na prática, transparência salarial é recompensada
     quando o salário é bom.
2. **Posição do pilar.** Em cada pilar, somam-se as posições dos critérios; a soma vira a posição do pilar.
3. **Ordem final.** Ordena-se pela soma das posições dos pilares. Empate na soma: vem antes quem está melhor em
   Atende; depois, quem está melhor em Requisitos; por fim, a ordem de cadastro.
4. **No lado B**, quem se candidatou à vaga vem primeiro (com o selo "interessado(a)"), na ordem da fórmula; depois vêm os demais.

**Agregador em uso: `rank_sum`.** Alternativas medidas na avaliação, nunca servidas sem os números mandarem:
- `rrf` (Reciprocal Rank Fusion): soma de 1/(60 + posição), que dá mais peso ao topo de cada critério;
- `weighted`: soma ponderada dos valores normalizados de 0 a 1 — requisitos 0,45, semântica 0,25, cargo 0,15, senioridade 0,15; Atende 0,7 e Interessa 0,3. Só como linha de base.

## 4. A régua absoluta: bom encaixe

A posição é relativa: muda quando a lista muda. Para contagens e para "o que mudaria", o Encaixe usa uma régua fixa.
Uma vaga é **bom encaixe** quando: passa nos filtros; você comprova **pelo menos 80%** dos
obrigatórios; e a senioridade está a **no máximo 1** nível de distância.
Uma vaga sem requisitos obrigatórios reconhecidos não pode ser avaliada e nunca conta como bom encaixe.

"A posição compara esta vaga com as outras da sua lista; bom encaixe é uma régua fixa." Por isso "3ª da lista" e
"ainda não é bom encaixe" podem aparecer juntos sem contradição.

**O que mudaria seu resultado.** Em cada vaga que ainda não é bom encaixe, o Encaixe mostra a menor mudança que a
tornaria um: uma skill (simulada como usada numa experiência recente) ou uma preferência (aceitar híbrido, aumentar
a distância, ajustar o mínimo). Ele fala sempre em bom encaixe, nunca em "subir N posições".

## 5. O ranking que aprende com seus swipes (`feedback-v1`)

O ranking servido por padrão é o `feedback-v1`. Ele acrescenta um terceiro pilar, **Histórico**, com o
mesmo peso dos outros dois — por isso não existe um peso extra para calibrar. Ele só entra depois de
**5 julgamentos**; antes disso, a ordem é exatamente a da fórmula estática.

    peso(swipe) = 0,5 ^ (dias desde o swipe / 21) × 0,5 ^ (revisões relevantes do perfil desde o swipe)
    histórico(item) = [ Σ curtidas peso × similaridade − Σ recusas λ × peso × similaridade ] / Σ pesos

- **Meia-vida de 21 dias:** um swipe de 21 dias atrás vale metade.
- **Desconto por revisão relevante (0,5):** cada mudança relevante de perfil desde o swipe multiplica o peso dele por 0,5.
  Uma revisão é relevante quando entra experiência ou formação nova, a senioridade muda, ou o conjunto de skills
  muda em pelo menos 3 skills.
- A similaridade usa a vaga (ou o perfil) **como era no momento do swipe**: quem evoluiu escapa da recusa antiga.

Efeito de cada motivo de recusa:

| Lado | Motivo | Efeito |
|---|---|---|
| C | área/cargo | feedback semântico negativo, λ = 1 |
| C | sem motivo | λ = 0,5 |
| C | empresa | só vagas daquela empresa perdem 0,15, com o mesmo decaimento |
| C | salário | sem penalidade semântica; vira preferência revelada no Explorar |
| C | modalidade | sem penalidade semântica; vira preferência revelada no Explorar |
| C | senioridade | sem penalidade semântica; vira preferência revelada no Explorar |
| B | skills | feedback semântico negativo, λ = 1 |
| B | sem motivo | λ = 0,5; só permitido para quem não se candidatou |
| B | senioridade | sem penalidade semântica |
| B | salário | sem penalidade semântica |
| B | local/modalidade | sem penalidade semântica |
| B | idioma | sem penalidade semântica |
| B | vaga preenchida ou pausada | nenhum efeito (não diz nada sobre o candidato) |


Os motivos são fixos, sem texto livre: o motivo da empresa vai para o candidato, e texto livre abriria espaço para
mensagens ofensivas ou vagas. Recusar **uma candidatura** exige um motivo da lista. O motivo do candidato é privado;
o recrutador só vê agregados com pelo menos 5 pessoas.

**Quando algo julgado volta:** um perfil recusado que teve revisão relevante depois da recusa volta para o
recrutador ("perfil atualizado desde sua última avaliação"); uma vaga em que sua candidatura não avançou volta
depois de uma revisão relevante sua ("seu perfil mudou desde a recusa"); uma vaga que você recusou volta se a vaga
mudou ("vaga atualizada").

## 6. Exploração: cartas sorteadas

A cada **10** cartas, uma vem sorteada da faixa entre os percentis 20 e
60 da sua lista, fora as 30 primeiras e o que você já viu. Ela diz que foi sorteada.
Sortear evita que o ranking se feche no que já acha bom; a faixa do meio evita mostrar vagas ruins. O aprendizado
usa todas as curtidas, inclusive as de cartas sorteadas, e a probabilidade de cada sorteio fica registrada para
correções futuras. Os filtros rodam antes de tudo: o aprendizado nunca ressuscita uma vaga filtrada.

## 7. Sessão e impressões

Uma carta conta como vista quando fica pelo menos 500 ms na tela. A sessão é renovada depois de
30 minutos sem atividade (recarregar a página não abre sessão nova). Os motivos de recusa aparecem por
3 s depois do swipe à esquerda e são opcionais para o candidato.

## 8. O que o recrutador vê e o que não vê

Até o encaixe, o card do candidato é **cego**: o recrutador não vê nome, contato, foto, idade, nomes das empresas, nomes das instituições de ensino. Promoções internas continuam
visíveis. O contato só é liberado quando os dois lados dão swipe à direita. Perfis criados por pessoas reais nascem
invisíveis; quem fica invisível sai também de todo agregado do lado B. Qualquer contagem menor que
5 aparece como "<5", e células de mapa com menos de 5 candidatos não aparecem.

## 9. O que vai para a IA

A IA (provedor `groq`, modelo `openai/gpt-oss-20b`) é opcional. Sem chave, tudo funciona com o extrator heurístico.
- **Seu CV** só é enviado se você marcar "Usar IA para ler meu CV (o texto é enviado ao provedor de LLM)", uma única vez no cadastro. A IA nunca reescreve um perfil já salvo.
- **Vagas** publicadas na plataforma e vagas de mercado que entram no top 20 de alguém podem ser relidas pela IA em segundo plano.
- Limites do plano gratuito configurados: 30 requisições/min, 1000 por dia, 8000 tokens/min, 200000 tokens/dia (documentação do Groq, plano gratuito, lida em 19/10/2026). Quando a IA falha ou o limite estoura, o Encaixe usa o extrator heurístico e avisa.

## 10. Fontes de vagas e câmbio

Fontes ligadas: nenhuma. Toda vaga mostra de onde veio, com link. Fontes desligadas no MVP: Greenhouse, Lever, GitHub, Ashby, Remotive, RemoteOK, Himalayas, We Work Remotely.
Salários em outras moedas são convertidos com câmbio aproximado (2026-10; BCE (frankfurter.dev) e ExchangeRate-API (open.er-api.com), 19/10/2026, arredondado) e marcados como "câmbio aproximado".

## 11. Exemplo resolvido, passo a passo

Uma pessoa analista de dados em Florianópolis (comprova SQL e Python; lista Power BI; mínimo de R$ 5.000/mês;
aceita vagas remotas e híbridas até 50 km) e três vagas. Os números abaixo são calculados agora pelo próprio motor de ranking.

| Vaga | Requisitos | Semântica | Cargo | Senioridade | Salário | Distância | Fuso |
|---|---|---|---|---|---|---|---|
| Analista de Dados (remota) | 2 de 3 obrigatórios comprovados (2 nos últimos 3 anos); 1 só listado(s), sem experiência com datas | similaridade 0,71 | similaridade de cargo 0,80 | vaga Júnior, perfil Júnior (mesmo nível) | até R$ 7.000/mês (+ 40% em relação ao seu mínimo) | vaga remota | 9 h de sobreposição no expediente 9h–18h |
| Cientista de Dados (híbrida) | 1 de 3 obrigatórios comprovados (1 nos últimos 3 anos) | similaridade 0,58 | similaridade de cargo 0,52 | vaga Pleno, perfil Júnior (1 nível de distância) | não informado | mesma cidade | não se aplica (vaga não remota) |
| Analista de BI (híbrida) | 1 de 3 obrigatórios comprovados (1 nos últimos 3 anos); 1,5 só listado(s), sem experiência com datas | similaridade 0,66 | similaridade de cargo 0,74 | vaga Júnior, perfil Júnior (mesmo nível) | até R$ 4.500/mês (− 10% em relação ao seu mínimo) | a 8 km | não se aplica (vaga não remota) |


Posições por critério (1 = melhor; empates recebem a média):

| Vaga | Req. | Sem. | Cargo | Sen. | **Atende** (soma → posição) | Sal. | Dist. | Fuso | **Interessa** (soma → posição) | **Total** | Ordem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Analista de Dados (remota) | 1 | 1 | 1 | 1,5 | 4,5 → 1ª | 1 | 1,5 | 2 | 4,5 → 1ª | 2 | **1ª** |
| Cientista de Dados (híbrida) | 3 | 3 | 3 | 3 | 12 → 3ª | 2 | 1,5 | 2 | 5,5 → 2ª | 5 | **3ª** |
| Analista de BI (híbrida) | 2 | 2 | 2 | 1,5 | 7,5 → 2ª | 3 | 3 | 2 | 8 → 3ª | 5 | **2ª** |


**Resultado:** a vaga "Analista de Dados (remota)" fica em 1º lugar com total 2 (Atende 1ª + Interessa 1ª). Quem tem a menor soma vem primeiro. "Analista de BI (híbrida)" e "Cientista de Dados (híbrida)" empatam na soma (5); "Analista de BI (híbrida)" vem antes porque está melhor em Atende (2ª contra 3ª).
