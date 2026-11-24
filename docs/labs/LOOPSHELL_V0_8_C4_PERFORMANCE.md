# LoopShell V0.8-C.4 — Qualificação pareada de desempenho

**PARTIAL para desempenho.** A referência independente e os três modos da
LoopShell produziram amostras válidas sob o mesmo perfil local. A meta da V0.7
de 28 quadros únicos pintados por segundo e p95 até 100 ms ficou fora das
oito janelas comparadas. A C.4 partiu da `main` em `b4e9fef`, após o merge do
PR #32 e a remoção da branch remota da C.3.
[Referência V0.7](../LOOPBRIDGE_V0_7.md#benchmark-methodology) ·
[Relatório C.3](LOOPSHELL_V0_8_C3_COMBINED_VIEWS.md) ·
[PR #32](https://github.com/LoopGolem/loopenvironment/pull/32).

## Revisão das falhas anteriores

Na tentativa anterior da Calculadora, o driver aceitou a operação
`app.launch` e aguardou aumento do contador de paints. O critério antigo
observa o fim do pipeline. O erro registrado deixa em aberto se houve
mudança, se o cliente recebeu quadro novo e se o GTK chegou a pintá-lo.
Na falha do Firefox, a condição antiga exigiu dez marcadores já pintados.
Ela também agrupa avanço da origem, recepção, decodificação e desenho.

A repetição da CLI V0.7 com `--view-only --seconds 8` avançou pelos
dois pontos, terminou com 125 marcadores pintados em 9,089 s e registrou
13,64 FPS. No piloto pareado, a mudança autorizada para `7` teve 11
quadros distintos recebidos e 11 paints após iniciar a observação da
mudança. No início da execução pareada houve 17 quadros distintos e 16
paints. A recepção e o paint de marcadores Firefox avançaram em cada
amostra do ensaio novo. As falhas históricas ficaram sem causa
determinada. A repetição afasta um defeito permanente no decoder ou no
caminho de streaming com a cena usada aqui.

Na C.3, o driver Combined fazia RPCs na thread que despachava o GTK e
introduzia uma espera de 20 ms ao bombear o loop. Retirar esse fator de
confusão permitiu executar o pareamento. A diferença entre os FPS de
C.3 e C.4 não mede isoladamente o custo do driver antigo.
[Driver V0.7](../../tools/loopbridge_presentation_demo.py) ·
[Driver C.3](../../tools/loopshell_combined_lab.py).

## Metodologia

- Debian 13.7 amd64, 2 vCPUs, Sway 1.10.1, wlroots 0.18.2, GTK 4.18.6,
  Firefox ESR 153.7.0esr, GTK Cairo e Sway Pixman. A saída externa do
  laboratório foi 1280×800 em escala 1. O desktop privado entregou
  BGRX 800×600 por stream V0.7.
- Cada rodada compartilhou o mesmo Sway descartável, o mesmo desktop privado
  e a mesma página offline `motion` do Firefox. Cada condição abriu um
  novo processo GTK. Na segunda rodada, a ordem dos modos foi invertida.
  As duas Combined usaram observador e delegado, com grants separados.
- O visualizador independente usou o mesmo `Viewer` V0.7 da CLI. Visual
  e Combined usaram as áreas reservadas da LoopShell. As regiões GTK de
  vídeo foram de 1260×754 no independente, 1000×574 no Visual, 1000×385
  na Combined e 490×385 por vídeo no modo duplo. As dimensões são a
  alocação do widget. O encaixe preserva a proporção da imagem.
- O driver ficou fora do processo GTK. Ele coletou `/proc`, abriu o cenário
  e gerou o mesmo ciclo autorizado de lease a cada quatro segundos em todos
  os modos. O processo GTK recebeu sinais de início e fim. A amostra usa o
  relógio do processo GTK e a leitura de feedback já em voo ocorre depois
  do limite. A amostragem de CPU usa o intervalo equivalente no driver.
- Cada janela começou depois de confirmar avanço de pelo menos dez
  marcadores Firefox pintados em cada vista. A amostra também exigiu
  avanço dos marcadores na recepção e no paint. Combined exigiu consultas
  de Activity. O piloto da Calculadora verificou a mudança para `7`
  pelo Bridge e registrou quadros distintos recebidos e pintados após
  a ação. A Calculadora serviu para verificar o caminho de apresentação.
  As metas de desempenho usam apenas a cena Firefox.

## Correlação e limites dos relógios

A instrumentação de cliente é opt-in e guarda até 8.192 registros numéricos
por stream e até 8.192 tempos de callback de status. A sequência binária
correlaciona as fases. O marcador Firefox fornece sua sequência de origem
e o timestamp em ms. A hora de parede do navegador é convertida para o
relógio monotônico do guest com pares de início e fim, cada um obtido com
leituras monotônicas em torno da leitura de hora. A conversão descarta
pares com incerteza maior que 1 ms ou deslocamento maior que 2 ms.
Também descarta idades fora de 0–2.000 ms. Intervalos negativos e
estágios sem dado ficam ausentes.

O timestamp binário existente é a leitura monotônica do helper no callback
`ready` do screencopy. `ready → cabeçalho no cliente` mede a primeira
entrega pelo caminho helper, pipe, broker e socket. `cabeçalho → payload`
mede o restante da leitura, incluindo a materialização dos bytes no cliente.
Os dois segmentos compartilham filas e escalonamento. Os dados não separam
cada syscall de escrita do helper ou splice no broker. O protocolo
continua idêntico.

A partir do payload, as sondas medem decodificação, entrada e sobrescrita
no mailbox de um quadro, idle, tick GTK, construção da textura, atribuição
ao widget, paint e feedback do compositor. Os p95 de segmentos são
calculados separadamente por população. Origem a feedback inclui apenas
quadros que chegaram ao compositor. O feedback corresponde ao Sway
headless. Nenhuma textura ou sequência de credenciais integra as evidências.

## Resultados pareados

| Cenário | FPS recebido R1 / R2 | FPS pintado R1 / R2 | p95 origem → feedback R1 / R2 | Mailbox sobrescrito R1 / R2 |
| --- | ---: | ---: | ---: | ---: |
| V0.7 independente | 29,49 / 25,97 | 26,23 / 24,04 | 145 / 171 ms | 11,1% / 7,7% |
| Visual ancorado | 26,64 / 22,39 | 24,11 / 20,13 | 152 / 177 ms | 9,3% / 10,4% |
| Combined | 25,79 / 24,16 | 16,66 / 14,31 | 194 / 248 ms | 35,8% / 40,8% |
| Duas Combined, observador | 14,45 / 14,58 | 5,33 / 4,68 | 396 / 376 ms | 63,1% / 67,6% |
| Duas Combined, delegado | 16,71 / 15,64 | 6,06 / 5,28 | 406 / 400 ms | 63,7% / 66,2% |

A fonte sustentou aproximadamente 52–56 atualizações/s com uma vista e
48/s com duas. Entre os marcadores extremos recebidos, 47–70% dos números
de origem estavam ausentes no cliente. Esse intervalo localiza a perda
antes da fila GTK e inclui atualizações que poderiam ter sido combinadas
pelo navegador ou pelo compositor. A diferença entre recebidos e
pintados cresceu novamente na Combined, sobretudo com dois vídeos.

| Segmento p95 | V0.7 / Visual | Uma Combined | Duas Combined |
| --- | ---: | ---: | ---: |
| Captura → cabeçalho | 8–9 ms | 9–10 ms | 13–16 ms |
| Cabeçalho → payload | 49–57 ms | 54–63 ms | 98–132 ms |
| Mailbox → tick | 24–32 ms | 40–41 ms | 84–108 ms |
| Construção da textura | 4–5 ms | 4–5 ms | 8–13 ms |
| Atribuição → paint | 44–50 ms | 79–98 ms | 128–142 ms |
| Intervalo entre ticks | 79–105 ms | 119–139 ms | 322–432 ms |

Construir a textura e executar o callback de status foram custos
menores diante da espera até o tick e o paint. As etapas a aprofundar
são a entrega do payload sob duas capturas concorrentes e a composição
após a atribuição da textura.
A diferença Visual–Combined é consistente no perfil ensaiado, com as
geometrias naturais de cada modo. A amostra não separa a parcela da
geometria, da composição da janela ou do custo de Cairo. O valor
histórico da V0.7 em outro compositor observador também não é uma
linha de base pareada.

## Recursos

Percentuais por processo são normalizados a um CPU lógico. O indicador
da VM é a fração ocupada da capacidade total do guest. O driver consumiu
0–0,13% de um CPU durante a amostragem. O conjunto de processos Firefox
consumiu aproximadamente 34–41% de um CPU. O RSS agregado soma páginas
compartilhadas uma vez por processo que as mapeia. A carga da VM foi de
83–88% com uma vista e de aproximadamente 91% com duas. `steal` observado
foi 0% nas janelas. A capacidade de reproduzir a mesma composição em um
guest com outros recursos ou pouca carga concorrente continua em aberto.

| Processo ou conjunto | Uma vista, CPU / RSS final | Duas Combined, CPU / RSS final |
| --- | --- | --- |
| GTK | 53–71% / 85–99 MiB | 65–66% / 110–111 MiB |
| Sway observador | 1,0–3,5% / 21–31 MiB | 1,1% / 31–33 MiB |
| Sway privado | 5,9–6,8% / 29 MiB | 6,6–7,2% / 31 MiB |
| Broker | 8–9% / 25 MiB | 14% / 25 MiB |
| Cada helper | 4,3–5,2% / 3,4–3,5 MiB | 3,7–3,9% / 3,4–3,5 MiB |

Na janela residual de cinco segundos, a mesma sessão e o Firefox
continuaram ativos. O cliente GTK e os helpers já haviam saído.
O broker consumiu 0,39% de um CPU e terminou em 25,14 MiB de RSS.

## Controle da rolagem externa

Em duas rodadas de 12 s, a variante de laboratório `combined-direct`
retirou somente o viewport de rolagem externo antes do map GTK.
Ela preservou a rolagem da Activity, a região de vídeo de 1000×385,
o `CairoRenderer`, a cena e os grants. A ordem foi invertida na segunda
rodada.

| Modo | FPS pintado R1 / R2 | p95 atribuição → paint R1 / R2 | Carga do guest R1 / R2 |
| --- | ---: | ---: | ---: |
| Combined com viewport | 11,48 / 10,74 | 123 / 123 ms | 89,16% / 89,17% |
| Combined direta | 15,07 / 13,44 | 96 / 95 ms | 85,83% / 87,24% |

A variante direta melhorou o trecho gráfico nas duas rodadas. A entrega
também variou, de 19,25–19,49 FPS recebidos no modo normal para
22,48–22,74 na variante. A diferença de carga e a melhora anterior
ao GTK deixam em aberto quanto do efeito vem do viewport e quanto
vem da competição por CPU. A rolagem externa preserva estados acessíveis
em janelas compactas. A mudança fica restrita ao controle experimental.
O produto mantém o layout e o transporte. A correção aplicada em C.4
foi separar o driver do GTK e exigir avanço verificável da origem.

## Reprodução

Use os dois pacotes layer-shell 1.0.4-2 e os hashes descritos em A.1.
Extraia em um diretório temporário curto, por exemplo `/tmp/lsc4.XXXXXX`.
Use a inicialização headless de A.1 com um runtime dentro desse diretório,
configuração `output * mode 1280x800 scale 1` e D-Bus descartável. Aponte
`SWAYSOCK`, `WAYLAND_DISPLAY` e `XDG_RUNTIME_DIR` para o Sway descartável.
[Reprodução A.1](LOOPSHELL_V0_8_A_LAYOUT.md#reprodução).

```sh
export LD_LIBRARY_PATH="$lib" GI_TYPELIB_PATH="$lib/girepository-1.0"
export GDK_BACKEND=wayland GSK_RENDERER=cairo GTK_A11Y=none GIO_USE_VFS=local
/usr/bin/python3 -B -m tools.loopshell_performance_lab \
  --root "$lab" --evidence "$lab/paired.json" --seconds 15 --repetitions 2
/usr/bin/python3 -B -m tools.loopshell_performance_lab \
  --root "$lab" --evidence "$lab/viewport.json" --seconds 12 --repetitions 2 \
  --modes combined combined-direct
```

A qualificação gráfica funcional usa o [driver C.3](../../tools/loopshell_combined_lab.py)
no mesmo tipo de Sway, com saída inicial de 1280×800. Execute
`LOOPSHELL_TEST_GTK=1 /usr/bin/python3 -B -m unittest discover -s tests`
no Sway descartável para ativar as regressões GTK.

## Validação e decisão

A integração gráfica foi repetida com críticos GTK fatais. O driver
incluiu Activity independente, Visual e Combined, verificou eventos reais,
as negativas de controle, revogações separadas e simultâneas, lacuna,
heartbeat, ressincronização e saída dos helpers. A sessão privada
continuou ativa após fechar as vistas e a LoopShell. Os 353 testes
passaram com GTK ativado. PID e hora de início, hash da configuração,
versão, saídas e workspaces do Sway principal coincidiram. Os dois
pacotes de layer-shell permaneceram ausentes da instalação do sistema.
[Evidência numérica e regressão](evidence/LOOPSHELL_V0_8_C4_PERFORMANCE.json).

A referência e a regressão funcional são reproduzíveis no perfil
ensaiado. A fluidez fica **PARTIAL**. O próximo controle de menor
escopo é comparar o tempo de composição com o mesmo tamanho de vídeo
e outro renderizador disponível no processo GTK, mantendo carga
concorrente e as etapas anteriores à textura sob observação.
D5, M1.3B e GTK 2→1 preservam suas qualificações independentes.
[Proposta documental D.1](../design/LOOPSHELL_V0_8_D1_PROPOSAL.md) ·
[D5](../design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5) ·
[M1.3B](M1_3B_TRUSTED_INPUT_FEASIBILITY.md) ·
[GTK 2→1](LOOPSHELL_V0_8_A_LAYOUT.md#fechamento-a2--escala-121).
