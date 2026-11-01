/** 시안의 폐업 단계 이름. 서버가 단계를 주기 전까지 자리만 보여준다 */
const STAGE_LABELS = ['준비', '철거', '신고', '정산', '세금']

/**
 * 홈 아래쪽의 폐업 단계 카드.
 *
 * 시안에서는 "지금은 원상복구·철거 단계"처럼 현재 단계를 굵게 칠하고, 누르면 로드맵으로 간다.
 * 지금은 현재 단계를 주는 API가 없다. 단계를 프론트에서 짐작해 칠하면 서버가 정하지 않은
 * 진행 상황을 확정된 것처럼 보여주게 되어, 막대를 비우고 다섯 이름을 모두 흐리게 둔다.
 * 로드맵 화면도 아직 없어 누를 곳이 없다.
 *
 * TODO(API): 현재 단계가 오면 제목에 단계 이름을 넣고 막대와 이름을 칠한다. 로드맵(7번 PR)으로 잇는다.
 */
export function HomeStageCard() {
  return (
    <section className="flex shrink-0 flex-col gap-3 rounded-2xl bg-bg-layer-default px-5 py-4.5 shadow-card">
      <h2 className="text-17 font-bold">폐업 단계</h2>
      <span aria-hidden="true" className="h-1.5 rounded-full bg-bg-neutral-weak" />
      <ol className="grid grid-cols-5">
        {STAGE_LABELS.map((label) => (
          <li key={label} className="text-center text-13 font-medium text-fg-neutral-subtle">
            {label}
          </li>
        ))}
      </ol>
      <p className="text-14 text-fg-neutral-muted">단계 정보는 곧 보여드릴게요</p>
    </section>
  )
}
