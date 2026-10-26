/** 与程序化球场同构的矢量海报，SSR、减少动态效果和 WebGL 故障时可用。 */
export function PitchPoster() {
  return <svg className="entry-poster" viewBox="0 0 1000 650" fill="none" aria-hidden="true">
    <defs>
      <radialGradient id="pitch-halo"><stop stopColor="var(--scene-light)" stopOpacity=".22" /><stop offset="1" stopColor="var(--scene-background)" stopOpacity="0" /></radialGradient>
      <linearGradient id="pitch-base" x2="0" y2="1"><stop stopColor="var(--surface-subtle)" /><stop offset="1" stopColor="var(--background)" /></linearGradient>
      <filter id="pitch-glow"><feGaussianBlur stdDeviation="3" /></filter>
    </defs>
    <ellipse cx="510" cy="410" rx="490" ry="240" fill="url(#pitch-halo)" />
    <g stroke="var(--scene-light)" opacity=".12">
      {[0, 1, 2, 3, 4].map((i) => <path key={i} d={`M ${55 - i * 14} ${355 + i * 15} L 490 ${177 - i * 12} L ${950 + i * 12} ${357 + i * 15} L 525 ${553 + i * 24} Z`} />)}
    </g>
    <path d="M120 345 490 195 895 355 895 390 525 540 120 380Z" fill="url(#pitch-base)" stroke="var(--scene-light)" strokeOpacity=".5" />
    <g transform="matrix(3.52 -1.43 5.96 2.35 120 345)">
      <rect width="105" height="68" fill="var(--scene-lawn)" fillOpacity=".7" />
      {[0, 2, 4, 6, 8].map((i) => <rect key={i} x={i * 10.5} width="10.5" height="68" fill="var(--scene-light)" opacity=".06" />)}
      <g stroke="var(--accent)" strokeWidth=".32" opacity=".85">
        <rect x="1" y="1" width="103" height="66" /><path d="M52.5 1v66" />
        <circle cx="52.5" cy="34" r="9.15" /><circle cx="52.5" cy="34" r=".5" fill="var(--accent)" />
        <path d="M1 13.84H16.5v40.32H1m103-40.32H88.5v40.32H104M1 24.84h5.5v18.32H1m103-18.32h-5.5v18.32h5.5" />
        <path d="M0 30.34v-5h-2v7.32H0m105-2.32v-5h2v7.32h-2" />
      </g>
      {[ [12, 34], [28, 16], [28, 34], [28, 52], [44, 24], [44, 44], [61, 17], [61, 48], [78, 25], [78, 45], [94, 34] ].map(([x, y], i) => <g key={i}>
        <path d={`M${x} ${y}v-3.5`} stroke="var(--accent)" strokeWidth=".35" opacity=".7" />
        <circle cx={x} cy={y - 3.8} r=".65" fill="var(--accent)" />
      </g>)}
    </g>
    <path d="M120 345 490 195 895 355 525 505Z" stroke="var(--accent)" strokeWidth="3" filter="url(#pitch-glow)" opacity=".8" />
    <path d="M120 345 490 195 895 355 525 505Z" stroke="var(--accent)" strokeWidth="1.5" />
  </svg>;
}
