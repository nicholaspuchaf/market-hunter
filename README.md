# Market Hunter

Central pessoal de vagas com frontend Svelte 5 + TypeScript, API Python/FastAPI,
coletor independente e SQLite. Tudo roda no seu computador.

```text
frontend/             Interface Svelte, Vite e pnpm
backend/app/          API HTTP e persistência SQLite
backend/collector/    Coleta Greenhouse, classificação e execução agendada
backend/tests/        Testes de coleta, persistência e API
```

## Rodar o MVP

Pré-requisitos: Python 3.12 ou superior, uv, Node.js 22.12 ou superior e pnpm 11.

Em um terminal, inicie o backend:

```sh
cd backend
uv sync --locked
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Em outro terminal, inicie o frontend:

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Abra o endereço exibido pelo Vite, normalmente http://127.0.0.1:5173.
O frontend encaminha `/api` ao backend local. Clique em **Buscar vagas** para a
primeira coleta. Não há vagas fictícias nem coleta de rede durante os testes.

## O que está disponível

- Fontes iniciais C6 Bank (`c6bank`) e iFood (`ifoodcarreiras`), pela API pública Greenhouse.
- Cadastro e pausa de outras empresas da Greenhouse pela interface.
- Listagem, busca textual e filtros por empresa, área, senioridade e modalidade.
- Radar inicial de tecnologia em todas as senioridades: Desenvolvimento, DevOps,
  Infraestrutura, IA, Dados, Segurança, Suporte de TI e cargos de departamentos de tecnologia.
- Tags combináveis de senioridade e filtro de seleção múltipla: Estágio, Júnior,
  Pleno, Sênior e Tech Lead. Especialista e Liderança aparecem separadamente;
  sem indicação no título, a vaga fica como Não informada.
- Favoritos, etapas da candidatura e notas para entrevistas, estudos e próximos passos.
- Tags de linguagens, plataformas (AWS, Azure, GCP e Linux) e outros requisitos
  citados no anúncio, como Docker, Kubernetes, Terraform, frameworks e bancos.
  Filtros por linguagem e plataforma. Tags podem incluir diferenciais;
  confirme na descrição quais requisitos são obrigatórios.
- Botão de ocultar/restaurar e página **Ocultos**. Vagas ocultas deixam de aparecer
  em Oportunidades; favoritar uma vaga mantém sua presença nas oportunidades.
  Ocultar não altera favorito, notas nem etapa e persiste entre coletas.
- Filtros opcionais para excluir vagas explicitamente afirmativas/direcionadas
  para mulheres, pessoas negras e pessoas com deficiência. Começam desmarcados
  e não excluem anúncios por uma declaração geral de diversidade.
- Histórico de mudanças na descrição e de execuções da coleta.
- Vagas indisponíveis e candidaturas permanecem no banco.

As categorias são regras de palavras no título e departamento, sem IA. Não se
deduz senioridade por número de anos ou modalidade a partir de texto genérico da
empresa. Campos ambíguos ficam como não informados e entram para revisão. Um
rótulo remoto, mesmo internacional, não confirma sozinho contratação no Brasil;
consulte o anúncio original. Localização compatível é apenas uma classificação
por termos, não uma garantia de elegibilidade.

Os filtros da tela são temporários. Por padrão, aparecem todas as vagas de tecnologia,
sem excluir níveis ou localidades. Marcar Júnior e Pleno mostra vagas de qualquer
um desses níveis, inclusive anúncios que possuem as duas tags. Ao desmarcar
**Somente vagas de tecnologia**, você pode consultar todas as vagas coletadas.
Favoritos e candidaturas incluem vagas fora do perfil e indisponíveis.

O backend também aceita `GET /api/jobs?technology_only=true&seniority=Júnior&seniority=Pleno`.
Use `visibility=visible` ou `visibility=hidden` para filtrar vagas ocultas,
`exclude_affirmative=Mulheres` (repetível) para filtrar públicos explicitamente
indicados e `PATCH /api/jobs/{id}` com `{"hidden": true}` ou `false` para ocultar/restaurar.
`language_tags`, `platform_tags`, `requirement_tags` e `affirmative_tags` são calculadas
a partir dos anúncios já salvos; não exigem nova coleta.
Os departamentos de origem são preservados a partir da próxima coleta. Vagas já
salvas são reclassificadas ao consultar a API, sem exigir uma nova busca na rede
nem alterar favoritos, notas ou etapas de candidaturas.

## Coleta automática local

Em um terceiro terminal:

```sh
cd backend
uv run python -m collector --watch
```

O processo verifica fontes pendentes a cada minuto e consulta cada empresa no
máximo uma vez a cada **48 horas**, contando a última tentativa. Isso também
evita repetir rapidamente uma fonte com falha. Enquanto estiver em execução,
retoma buscas pendentes depois de suspensão do PC. Se o processo for encerrado
ou o PC reiniciar, é necessário iniciá-lo novamente. Nenhum serviço do sistema
é instalado automaticamente.

Para executar uma vez, respeitando o intervalo:

```sh
uv run python -m collector
```

Para uma execução manual imediata:

```sh
uv run python -m collector --force
```

O botão da interface também força a busca. Execuções manuais respeitam um
intervalo mínimo de um minuto por fonte e não se sobrepõem a uma coleta em curso.
Uma chamada por empresa retorna a lista com descrições. Não há retentativas
automáticas dentro da execução; `403`, `429` e outras falhas ficam registradas
para revisão. Uma fonte com erro não altera suas vagas nem impede outras fontes.

Após duas coletas completas bem-sucedidas sem uma vaga, ela é marcada como
indisponível na fonte. Isso não comprova encerramento pela empresa. Se reaparecer,
é reativada. Favoritos, etapa e notas são preservados nas atualizações.

## Dados e backup

O banco é criado em `backend/data/market-hunter.sqlite3`, independentemente do
diretório de onde a aplicação for iniciada. Para outro caminho, defina
`MARKET_HUNTER_DB` com um caminho absoluto tanto na API quanto no coletor.

Para um backup consistente, execute a partir de `backend/`:

```sh
uv run python -m app.backup data/backup.sqlite3
```

O SQLite está em modo WAL. Evite copiar somente o arquivo principal enquanto há
gravações em andamento; use a API de backup acima ou pare os processos antes de copiar.

A aplicação não possui autenticação e deve continuar vinculada a `127.0.0.1`.
O texto de vagas é exibido como texto, sem executar o HTML recebido. Não são
necessários cookies pessoais, credenciais Greenhouse ou serviços de IA.

## Verificação

```sh
cd backend
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

```sh
cd frontend
pnpm check
pnpm build
```

`pnpm preview` serve o build local e também encaminha `/api` para a API na porta 8000.

## Próximas etapas

Amazon e BTG ainda não têm coletores. Também ficam para uma próxima versão:
análise de currículo, recomendações de estudo com IA, pesquisa sobre empresas,
notificações, instalação automática do agendador e hospedagem em nuvem.
