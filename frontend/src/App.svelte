<script lang="ts">
  import { onMount } from 'svelte';
  import { api, stages, type Job, type Source, type Run, type Stage, type Revision } from './api';

  let jobs = $state<Job[]>([]);
  let sources = $state<Source[]>([]);
  let runs = $state<Run[]>([]);
  let page = $state('discover');
  let loading = $state(true);
  let collecting = $state(false);
  let saving = $state(false);
  let error = $state('');
  let message = $state('');
  let search = $state('');
  let company = $state('');
  let area = $state('');
  let mode = $state('');
  let levels = $state<string[]>([]);
  let language = $state('');
  let platform = $state('');
  let excludedGroups = $state<string[]>([]);
  let pendingJobs = $state<number[]>([]);
  let profileOnly = $state(true);
  let showInactive = $state(false);
  let selectedId = $state<number | null>(null);
  let notes = $state('');
  let draftStage = $state<Stage>('new');
  let dirty = $state(false);
  let revisions = $state<Revision[]>([]);
  let sourceName = $state('');
  let sourceBoard = $state('');
  let detailsDialog = $state<HTMLDialogElement>();
  const areas = ['Desenvolvimento', 'DevOps', 'Infraestrutura', 'IA', 'Dados', 'Segurança', 'Suporte de TI', 'Tecnologia'];
  const seniorityOptions = ['Estágio', 'Júnior', 'Pleno', 'Sênior', 'Tech Lead', 'Especialista', 'Liderança', 'Não informada'];
  const affirmativeOptions = ['Mulheres', 'Pessoas negras', 'PcD'];
  const languageOptions = $derived([...new Set(jobs.flatMap(job => job.language_tags))].sort());
  const platformOptions = ['AWS', 'Azure', 'GCP', 'Linux'];
  const selected = $derived(jobs.find(job => job.id === selectedId));
  $effect(() => {
    if (selected && detailsDialog && !detailsDialog.open) detailsDialog.showModal();
  });
  const normalize = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const inProfile = (job: Job) => job.categories.length > 0;
  const profileJobs = $derived(jobs.filter(job => job.active && !job.hidden && inProfile(job)));
  const applications = $derived(jobs.filter(job => !['new', 'archived'].includes(job.stage)));
  const filtered = $derived(jobs.filter(job => {
    if (page === 'favorites' && !job.favorite) return false;
    if (page === 'hidden' && !job.hidden) return false;
    if (page === 'applications' && ['new', 'archived'].includes(job.stage)) return false;
    if (page === 'discover') {
      if (job.hidden) return false;
      if (!showInactive && !job.active) return false;
      if (profileOnly && !inProfile(job)) return false;
    }
    return (!search || normalize(`${job.title} ${job.description} ${job.company}`).includes(normalize(search)))
      && (!company || job.company === company)
      && (!area || job.categories.includes(area))
      && (!mode || job.work_mode === mode)
      && (!language || job.language_tags.includes(language))
      && (!platform || job.platform_tags.includes(platform))
      && !job.affirmative_tags.some(group => excludedGroups.includes(group))
      && (!levels.length || levels.some(value => (job.seniority_tags.length ? job.seniority_tags : ['Não informada']).includes(value)));
  }));
  const recentSuccess = $derived(sources.map(source => source.last_success).filter((date): date is string => !!date).sort().at(-1));

  function date(value?: string | null) {
    return value ? new Date(value).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : 'Ainda não coletada';
  }

  async function refresh() {
    const [newJobs, newSources, newRuns] = await Promise.all([
      api<Job[]>('/jobs'), api<Source[]>('/sources'), api<Run[]>('/runs'),
    ]);
    jobs = newJobs; sources = newSources; runs = newRuns;
  }

  onMount(async () => {
    try { await refresh(); } catch (err) { error = (err as Error).message; }
    finally { loading = false; }
  });

  async function collect() {
    collecting = true; error = ''; message = '';
    try {
      const result = await api<{ results: { source: string; status: string; count?: number }[] }>('/collect', 'POST');
      await refresh();
      const failures = result.results.filter(item => item.status === 'error');
      if (failures.length) error = `Não foi possível atualizar: ${failures.map(item => item.source).join(', ')}. Veja o motivo em Fontes. As vagas salvas foram preservadas.`;
      else if (result.results.every(item => item.status === 'skipped')) message = 'Nenhuma coleta iniciada. As fontes estão pausadas, em coleta ou foram consultadas há menos de um minuto.';
      else message = 'Coleta concluída. Suas oportunidades estão atualizadas.';
    } catch (err) { error = (err as Error).message; }
    finally { collecting = false; }
  }

  function canLeave() { return !dirty || window.confirm('Descartar as alterações ainda não salvas?'); }
  function navigate(value: string) {
    if (!canLeave()) return;
    page = value; selectedId = null; dirty = false; revisions = [];
  }
  function open(job: Job) {
    if (saving || !canLeave()) return;
    selectedId = job.id; notes = job.notes; draftStage = job.stage; dirty = false; revisions = [];
    message = ''; error = '';
  }
  async function favorite(job: Job) {
    if (pendingJobs.includes(job.id)) return;
    pendingJobs = [...pendingJobs, job.id];
    error = '';
    try {
      await api(`/jobs/${job.id}`, 'PATCH', { favorite: !job.favorite });
      jobs = jobs.map(item => item.id === job.id ? { ...item, favorite: !job.favorite } : item);
    } catch (err) { error = (err as Error).message; }
    finally { pendingJobs = pendingJobs.filter(id => id !== job.id); }
  }
  async function toggleHidden(job: Job) {
    if (pendingJobs.includes(job.id)) return;
    pendingJobs = [...pendingJobs, job.id];
    error = '';
    try {
      await api(`/jobs/${job.id}`, 'PATCH', { hidden: !job.hidden });
      jobs = jobs.map(item => item.id === job.id ? { ...item, hidden: !job.hidden } : item);
      message = job.hidden ? 'Vaga restaurada nas oportunidades.' : 'Vaga movida para Ocultos.';
    } catch (err) { error = (err as Error).message; }
    finally { pendingJobs = pendingJobs.filter(id => id !== job.id); }
  }
  async function save() {
    if (!selected) return;
    const id = selected.id; const savedNotes = notes; const savedStage = draftStage;
    saving = true; error = '';
    try {
      await api(`/jobs/${id}`, 'PATCH', { notes: savedNotes, stage: savedStage });
      jobs = jobs.map(job => job.id === id ? { ...job, notes: savedNotes, stage: savedStage } : job);
      dirty = false; message = 'Candidatura atualizada.';
    } catch (err) { error = (err as Error).message; }
    finally { saving = false; }
  }
  async function history() {
    if (!selected) return;
    const id = selected.id;
    try {
      const items = await api<Revision[]>(`/jobs/${id}/revisions`);
      if (selectedId === id) { revisions = items; if (!items.length) message = 'Nenhuma alteração de descrição registrada.'; }
    } catch (err) { error = (err as Error).message; }
  }
  async function addSource(event: SubmitEvent) {
    event.preventDefault(); saving = true; error = '';
    try {
      await api('/sources', 'POST', { name: sourceName.trim(), board: sourceBoard.trim() });
      sourceName = ''; sourceBoard = ''; await refresh(); message = 'Fonte cadastrada. Clique em Buscar vagas para consultar.';
    } catch (err) { error = (err as Error).message; }
    finally { saving = false; }
  }
  async function toggleSource(source: Source) {
    try { await api(`/sources/${source.id}`, 'PATCH', { enabled: !source.enabled }); await refresh(); }
    catch (err) { error = (err as Error).message; }
  }
  function resetFilters() { search = ''; company = ''; area = ''; mode = ''; levels = []; language = ''; platform = ''; excludedGroups = []; profileOnly = true; showInactive = false; }
</script>

<svelte:window onbeforeunload={(event) => { if (dirty) { event.preventDefault(); event.returnValue = ''; } }} />

<div class="app-shell">
  <aside class="sidebar">
    <a class="brand" href="/" aria-label="Market Hunter, início">
<span class="brand-icon">m<span>↗</span>
</span>
<span>market<span class="brand-light">hunter</span>
<small>SEU PRÓXIMO PASSO</small>
</span>
</a>
    <div class="workspace">
<span class="avatar">N</span>
<div>Meu espaço<small>Busca pessoal de vagas</small>
</div>
<span class="workspace-dot">
</span>
</div>
    <p class="nav-label">EXPLORAR</p>
    <nav aria-label="Navegação principal">
      <button class:active={page === 'discover'} onclick={() => navigate('discover')}>
<span>⌕</span> Oportunidades <b>{profileJobs.length}</b>
</button>
      <button class:active={page === 'favorites'} onclick={() => navigate('favorites')}>
<span>☆</span> Favoritos <b>{jobs.filter(job => job.favorite).length}</b>
</button>
      <button class:active={page === 'hidden'} onclick={() => navigate('hidden')} aria-label="Vagas ocultas">
<span>⊘</span> Ocultos <b>{jobs.filter(job => job.hidden).length}</b>
</button>
      <button class:active={page === 'applications'} onclick={() => navigate('applications')}>
<span>▤</span> Candidaturas <b>{applications.length}</b>
</button>
      <button class:active={page === 'sources'} onclick={() => navigate('sources')}>
<span>⌁</span> Fontes de vagas</button>
    </nav>
    <div class="profile-card">
<span class="eyebrow">SEU RADAR</span>
<h3>Tecnologia, com direção.</h3>
<p>Todas as senioridades</p>
<div class="mini-tags">{#each areas as name}<span>{name}</span>{/each}</div>
<p class="location-note">◎ Remoto · Brasil e exterior<br />◎ Campinas e São Paulo</p>
</div>
    <div class="local-status">
<span>
</span> No seu computador<small>Seus dados ficam com você.</small>
</div>
  </aside>

  <main>
    <header class="topbar">
<span>Meu espaço <span class="slash">/</span> <strong>{page === 'sources' ? 'Fontes de vagas' : page === 'favorites' ? 'Favoritos' : page === 'hidden' ? 'Ocultos' : page === 'applications' ? 'Candidaturas' : 'Oportunidades'}</strong>
</span>
<span class="local-badge">
<i>
</i> Espaço pessoal</span>
</header>
    <div class="main-content">
      <div class="page-heading">
<div>
<p class="eyebrow">MENOS ABAS. MAIS POSSIBILIDADES.</p>
<h1>{page === 'sources' ? 'Seu radar começa aqui.' : page === 'favorites' ? 'Vale ficar de olho.' : page === 'hidden' ? 'Fora do radar. Sempre recuperáveis.' : page === 'applications' ? 'Cada passo, no seu tempo.' : 'Seu próximo passo começa aqui.'}</h1>
<p class="subtitle">{page === 'sources' ? 'Escolha quais empresas acompanhar e confira a saúde das coletas.' : page === 'favorites' ? 'As oportunidades que você escolheu acompanhar mais de perto.' : page === 'hidden' ? 'Vagas que você ocultou. Restaure quando quiser vê-las nas oportunidades.' : page === 'applications' ? 'Organize processos, entrevistas e o que você aprendeu pelo caminho.' : 'Oportunidades reunidas para você encontrar o que faz sentido.'}</p>
</div>
<button class="primary" onclick={collect} disabled={collecting || loading}>
<span class:spinning={collecting}>↻</span> {collecting ? 'Buscando vagas…' : 'Buscar vagas'}</button>
</div>
      {#if error}<div class="notice error" role="alert">{error}<button aria-label="Fechar erro" onclick={() => error = ''}>×</button>
</div>{/if}
      {#if message}<div class="notice success" role="status">{message}<button aria-label="Fechar aviso" onclick={() => message = ''}>×</button>
</div>{/if}

      <section class="stats" aria-label="Resumo da busca">
        <div>
<span>NO SEU RADAR</span>
<strong>{profileJobs.length}<i>↗</i>
</strong>
<p>Vagas de tecnologia coletadas</p>
</div>
        <div>
<span>CANDIDATURAS</span>
<strong>{jobs.filter(job => ['applied', 'interview', 'offer', 'rejected'].includes(job.stage)).length}<i>▤</i>
</strong>
<p>Seu movimento até aqui</p>
</div>
        <div>
<span>EM ENTREVISTAS</span>
<strong>{jobs.filter(job => job.stage === 'interview').length}<i>◷</i>
</strong>
<p>Conversas que abrem portas</p>
</div>
        <div>
<span>FONTES ATIVAS</span>
<strong>{sources.filter(source => source.enabled).length}<i>⌁</i>
</strong>
<p>{recentSuccess ? `Atualizado em ${date(recentSuccess)}` : 'Prontas para a primeira busca'}</p>
</div>
      </section>

      {#if page === 'sources'}
        <section class="sources-section">
<div class="section-title">
<h2>Empresas acompanhadas</h2>
<span>Greenhouse</span>
</div>
          <p class="muted">As buscas automáticas respeitam um intervalo de 48 horas. Amazon e BTG aguardam integração.</p>
          <div class="source-grid">{#each sources as source}<article class="source-card">
<div class="source-title">
<div class="company-icon">{source.name.slice(0, 2)}</div>
<h3>{source.name}</h3>
<span class:disabled={!source.enabled} class="source-status">{source.enabled ? 'Ativa' : 'Pausada'}</span>
</div>
<p>{source.job_count} vagas abertas salvas</p>
<small>Última coleta: {date(source.last_success)}</small>{#if source.last_error}<p class="source-error">{source.last_error}</p>{/if}<button class="secondary" onclick={() => toggleSource(source)}>{source.enabled ? 'Pausar fonte' : 'Ativar fonte'}</button>
</article>{/each}</div>
          <form class="source-form" onsubmit={addSource}>
<h3>Adicionar empresa na Greenhouse</h3>
<p class="muted">Use o identificador do endereço job-boards.greenhouse.io/<strong>empresa</strong>.</p>
<div class="form-row">
<label>Nome da empresa<input required maxlength="100" bind:value={sourceName} placeholder="Ex.: Minha empresa" />
</label>
<label>Identificador do quadro<input required pattern={'[a-zA-Z0-9_-]{1,100}'} bind:value={sourceBoard} placeholder="Ex.: ifoodcarreiras" />
</label>
<button class="primary" disabled={saving}>Adicionar fonte</button>
</div>
</form>
          <div class="section-title">
<h2>Últimas coletas</h2>
</div>
<div class="run-list">{#each runs as run}<div>
<strong>{run.company}</strong>
<span>{date(run.started_at)}</span>
<span class:error-text={run.status === 'error'}>{run.status === 'success' ? `${run.count} vagas consultadas` : run.status === 'running' ? 'Em andamento' : 'Falha na coleta'}</span>
</div>{:else}<p class="muted">Nenhuma coleta executada.</p>{/each}</div>
        </section>
      {:else}
        <section class="opportunities">
<div class="section-title">
<h2>{page === 'favorites' ? 'Suas vagas favoritas' : page === 'hidden' ? 'Suas vagas ocultas' : page === 'applications' ? 'Seus processos' : 'Explore as oportunidades'} <span class="count-pill">{filtered.length}</span>
</h2>
<span class="muted">Mais recentes primeiro</span>
</div>
          <div class="filters">
<label class="search-field">
<span>⌕</span>
<input aria-label="Buscar por cargo, empresa ou tecnologia" bind:value={search} placeholder="Cargo, empresa ou tecnologia…" />
</label>
<select aria-label="Empresa" bind:value={company}>
<option value="">Todas as empresas</option>{#each sources as source}<option value={source.name}>{source.name}</option>{/each}</select>
<select aria-label="Área" bind:value={area}>
<option value="">Todas as áreas</option>{#each areas as name}<option>{name}</option>{/each}</select>

<select aria-label="Modalidade" bind:value={mode}>
<option value="">Todas as modalidades</option>{#each ['Remoto', 'Híbrido', 'Presencial', 'Não informado'] as name}<option>{name}</option>{/each}</select>
</div>
          <div class="technology-filters">
  <label>Linguagem<select bind:value={language}><option value="">Todas as linguagens</option>{#each languageOptions as name}<option>{name}</option>{/each}</select></label>
  <label>Plataforma / sistema<select bind:value={platform}><option value="">Todas as plataformas</option>{#each platformOptions as name}<option>{name}</option>{/each}</select></label>
</div>
          <fieldset class="seniority-filters">
  <legend>Senioridade <span>Selecione uma ou mais. Sem seleção, todos os níveis aparecem.</span></legend>
  <div>{#each seniorityOptions as name}
    <label class="seniority-option" class:checked={levels.includes(name)}><input type="checkbox" bind:group={levels} value={name} />{name}</label>
  {/each}</div>
</fieldset>
<fieldset class="seniority-filters affirmative-filters">
  <legend>Excluir vagas direcionadas <span>Aplica-se a anúncios com indicação explícita de público.</span></legend>
  <div>{#each affirmativeOptions as group}
    <label class="seniority-option" class:checked={excludedGroups.includes(group)}><input type="checkbox" bind:group={excludedGroups} value={group} />{group}</label>
  {/each}</div>
</fieldset>
<div class="filter-footer">
<div>{#if page === 'discover'}<label class="checkbox">
<input type="checkbox" bind:checked={profileOnly} /> Somente vagas de tecnologia</label>
<label class="checkbox">
<input type="checkbox" bind:checked={showInactive} /> Incluir indisponíveis</label>{:else}<span class="muted">Inclui vagas fora do perfil e indisponíveis que você acompanha.</span>{/if}</div>
<button class="text-button" onclick={resetFilters}>Limpar filtros</button>
</div>
          {#if page === 'discover' && profileOnly}<p class="profile-hint">Seu radar inclui vagas para revisar. Modalidade, senioridade ou elegibilidade no Brasil podem precisar de confirmação no anúncio.</p>{/if}
          {#if loading}<div class="empty">
<span class="empty-symbol">◌</span>
<h3>Preparando seu radar…</h3>
</div>
          {:else if !filtered.length}<div class="empty">
<span class="empty-symbol">⌕</span>
<h3>{jobs.length ? 'Nenhuma vaga com esses filtros.' : 'Seu próximo passo ainda está por aqui.'}</h3>
<p>{jobs.length ? 'Ajuste os filtros ou desative o filtro de tecnologia para explorar outras oportunidades.' : 'Faça a primeira busca para reunir vagas do C6 Bank e do iFood no seu espaço.'}</p>
<button class="secondary" onclick={jobs.length ? resetFilters : collect} disabled={collecting}>{jobs.length ? 'Redefinir filtros' : 'Fazer primeira busca'} <span>↗</span>
</button>
</div>
          {:else}<div class="job-grid">{#each filtered as job (job.id)}<article class="job-card" class:selected={selectedId === job.id}>
<div class="card-top">
<div class="company-line">
<span class="company-icon" class:ifood={job.company === 'iFood'}>{job.company === 'iFood' ? 'if' : job.company.slice(0, 2)}</span>
<strong>{job.company}</strong>
</div>
<div class="card-actions"><button class="hide-job" disabled={pendingJobs.includes(job.id)} onclick={() => toggleHidden(job)} aria-label={job.hidden ? 'Restaurar vaga nas oportunidades' : 'Ocultar vaga'} title={job.hidden ? 'Restaurar vaga' : 'Ocultar vaga'}>{job.hidden ? '↶' : '⊘'}</button>
<button class="favorite" disabled={pendingJobs.includes(job.id)} class:is-favorite={job.favorite} aria-label={job.favorite ? 'Remover dos favoritos' : 'Adicionar aos favoritos'} aria-pressed={job.favorite} onclick={() => favorite(job)}>{job.favorite ? '★' : '☆'}</button></div>
</div>
<button class="job-title" onclick={() => open(job)}>{job.title}</button>
<p class="job-location">◎ {job.location}</p>
<div class="tags">
{#each job.seniority_tags.length ? job.seniority_tags : ['Não informada'] as tag}<span>{tag}</span>{/each}
<span>{job.work_mode}</span>{#each job.categories as category}<span class="area-tag">{category}</span>{/each}</div>
<div class="tags requirement-tags" aria-label="Tecnologias citadas no anúncio">
{#each [...job.language_tags, ...job.platform_tags, ...job.requirement_tags] as tag}<span class="technology-tag">{tag}</span>{/each}
{#each job.affirmative_tags as tag}<span class="affirmative-tag">Afirmativa: {tag}</span>{/each}
{#if job.hidden}<span>Oculta</span>{/if}
</div>
<div class="card-bottom">
<span class="job-state" class:review={job.location_fit === 'Revisar' || job.seniority === 'Não informada'}>{!job.active ? 'Indisponível na fonte' : job.stage !== 'new' ? stages[job.stage] : job.location_fit === 'Revisar' || job.seniority === 'Não informada' ? 'Conferir requisitos' : 'Ver requisitos no anúncio'}</span>
<button class="text-button" onclick={() => open(job)}>Ver vaga <span>↗</span>
</button>
</div>
</article>{/each}</div>{/if}
        </section>
      {/if}
      <footer>Uma oportunidade de cada vez.<span>Market Hunter · Seu espaço de carreira</span>
</footer>
    </div>
  </main>
</div>

{#if selected}
  <dialog
    class="detail-overlay"
    bind:this={detailsDialog}
    aria-labelledby="vacancy-title"
    oncancel={(event) => {
      event.preventDefault();
      if (!saving && canLeave()) { selectedId = null; dirty = false; }
    }}
  >
    <button class="detail-backdrop" aria-label="Fechar detalhes" disabled={saving}
      onclick={() => { if (canLeave()) { selectedId = null; dirty = false; } }}></button>
    <aside class="detail-panel" aria-label="Detalhes da vaga">
      <div class="detail-toolbar">
        <div class="detail-header">
          <span class="detail-header-label"><span aria-hidden="true">↗</span> EXPLORAR UMA POSSIBILIDADE</span>
          <button class="close-button" disabled={saving} aria-label="Fechar detalhes"
            onclick={() => { if (canLeave()) { selectedId = null; dirty = false; } }}>×</button>
        </div>
        <nav class="detail-navigation" aria-label="Seções da vaga">
          <button onclick={() => detailsDialog?.querySelector('#vacancy-overview')?.scrollIntoView({ block: 'start' })}>Visão geral</button>
          <button onclick={() => detailsDialog?.querySelector('#vacancy-description')?.scrollIntoView({ block: 'start' })}>Descrição</button>
          <button onclick={() => detailsDialog?.querySelector('#vacancy-tracking')?.scrollIntoView({ block: 'start' })}>Meu acompanhamento {#if dirty}<span class="unsaved-dot" aria-label="Alterações não salvas"></span>{/if}</button>
        </nav>
      </div>

      <div class="detail-content">
        {#if error}<div class="notice error" role="alert">{error}</div>{/if}
        {#if message}<div class="notice success" role="status">{message}</div>{/if}

        <section class="detail-hero" id="vacancy-overview" aria-labelledby="vacancy-title">
          <div class="detail-company-row">
            <div class="detail-company">
              <span class="company-icon" class:ifood={selected.company === 'iFood'}>{selected.company === 'iFood' ? 'if' : selected.company.slice(0, 2)}</span>
              <div><strong>{selected.company}</strong><span>Oportunidade de carreira</span></div>
            </div>
            <span class="detail-availability" class:unavailable={!selected.active}>
              <i></i>{selected.hidden ? 'Oculta do radar' : selected.active ? 'Disponível na fonte' : 'Indisponível na fonte'}
            </span>
          </div>
          <h2 id="vacancy-title">{selected.title}</h2>
          <div class="tags detail-category-tags">
            {#each selected.categories as category}<span class="area-tag">{category}</span>{/each}
            {#each selected.affirmative_tags as tag}<span class="affirmative-tag">Afirmativa: {tag}</span>{/each}
          </div>
          <div class="detail-facts">
            <div><span class="fact-label">LOCALIZAÇÃO</span><strong>{selected.location}</strong></div>
            <div><span class="fact-label">MODALIDADE</span><strong>{selected.work_mode}</strong></div>
            <div><span class="fact-label">SENIORIDADE</span><strong>{selected.seniority}</strong></div>
          </div>
          <div class="detail-actions">
            <a class="primary" href={selected.url} target="_blank" rel="noopener noreferrer">Abrir anúncio original <span aria-hidden="true">↗</span></a>
            <button class="secondary detail-favorite" class:marked={selected.favorite}
              disabled={pendingJobs.includes(selected.id)} aria-pressed={selected.favorite} onclick={() => favorite(selected)}>
              <span aria-hidden="true">{selected.favorite ? '★' : '☆'}</span>{selected.favorite ? 'Favoritada' : 'Favoritar'}
            </button>
            <button class="detail-hide" disabled={pendingJobs.includes(selected.id)} onclick={() => toggleHidden(selected)}>
              <span aria-hidden="true">{selected.hidden ? '↶' : '⊘'}</span>{selected.hidden ? 'Restaurar vaga' : 'Ocultar'}
            </button>
          </div>
        </section>

        <section class="detail-section requirements-section" aria-labelledby="requirements-title">
          <div class="detail-section-heading"><span class="section-marker" aria-hidden="true">⌘</span><div><h3 id="requirements-title">O que está no radar desta vaga</h3><p>Tecnologias e conhecimentos citados no anúncio.</p></div></div>
          <div class="requirement-groups">
            {#each [
              { label: 'Linguagens', tags: selected.language_tags },
              { label: 'Cloud e sistemas', tags: selected.platform_tags },
              { label: 'Ferramentas e conhecimentos', tags: selected.requirement_tags },
            ] as group}
              <div class="requirement-group"><h4>{group.label}</h4><div class="tags requirement-tags">
                {#each group.tags as tag}<span class="technology-tag">{tag}</span>{:else}<span class="no-requirement">Não identificado no texto</span>{/each}
              </div></div>
            {/each}
          </div>
          <p class="detail-footnote">As tags podem incluir diferenciais. Confira na descrição quais requisitos são obrigatórios.</p>
        </section>

        <section class="detail-section" id="vacancy-description" aria-labelledby="description-title">
          <div class="detail-section-heading"><span class="section-marker" aria-hidden="true">≡</span><div><h3 id="description-title">Sobre a oportunidade</h3><p>A descrição publicada pela empresa, reunida aqui.</p></div></div>
          <div class="description vacancy-description">
            {#each (selected.description || 'Descrição não fornecida. Consulte o anúncio original.').split(/\n\s*\n/) as paragraph}
              <p>{paragraph}</p>
            {/each}
          </div>
        </section>

        <section class="tracking" id="vacancy-tracking" aria-labelledby="tracking-title">
          <div class="detail-section-heading"><span class="section-marker" aria-hidden="true">▤</span><div><h3 id="tracking-title">Seu próximo movimento</h3><p>Um espaço para organizar o que vem depois.</p></div></div>
          <label>Etapa da candidatura
            <select bind:value={draftStage} onchange={() => dirty = true} disabled={saving}>
              {#each Object.entries(stages) as [key, label]}<option value={key}>{label}</option>{/each}
            </select>
          </label>
          <label>Notas, entrevistas e próximos passos
            <textarea rows="7" bind:value={notes} oninput={() => dirty = true} disabled={saving}
              placeholder="O que vale estudar para esta vaga?\nO que descobri sobre a empresa?\nQual é o próximo passo?"></textarea>
          </label>
          <div class="tracking-footer"><span class:pending={dirty} role="status">{dirty ? 'Você tem alterações para salvar' : 'Seu acompanhamento está salvo'}</span><button class="primary" onclick={save} disabled={saving || !dirty}>{saving ? 'Salvando…' : dirty ? 'Salvar acompanhamento' : 'Tudo salvo ✓'}</button></div>
        </section>

        <div class="detail-source-note">
          <span aria-hidden="true">ⓘ</span><p>Confirme modalidade, senioridade e contratação no Brasil no anúncio original. As classificações são extraídas automaticamente do texto.</p>
        </div>
        <section class="detail-history" aria-labelledby="history-title">
          <div class="detail-section-heading"><div><h3 id="history-title">Histórico da oportunidade</h3></div></div>
          <dl class="detail-meta"><div><dt>Encontrada em</dt><dd>{date(selected.first_seen)}</dd></div><div><dt>Última confirmação</dt><dd>{date(selected.last_seen)}</dd></div></dl>
          <button class="text-button" onclick={history}>Consultar versões anteriores <span aria-hidden="true">↗</span></button>
          {#each revisions as revision}<details><summary>Versão registrada em {date(revision.recorded_at)}</summary><div class="description">{revision.description}</div></details>{/each}
        </section>
      </div>
    </aside>
  </dialog>
{/if}
