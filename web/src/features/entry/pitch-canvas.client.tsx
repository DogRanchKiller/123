"use client";

import { Component, memo, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Canvas } from "@react-three/fiber";
import { PitchScene } from "./pitch-scene";
import { PitchPoster } from "./pitch-poster";

class SceneBoundary extends Component<{ children: ReactNode; onFailure: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { this.props.onFailure(); }
  render() { return this.state.failed ? null : this.props.children; }
}

function PitchCanvas() {
  const holder=useRef<HTMLDivElement>(null);
  const [environment,setEnvironment]=useState({ ready:false, compact:false, reduced:true, visible:true, onscreen:true, supported:false });
  const [enabled,setEnabled]=useState<boolean | null>(null);
  const [failed,setFailed]=useState(false), [ready,setReady]=useState(false), [low,setLow]=useState(false);
  const markReady=useCallback(() => setReady(true), []);
  const markFailed=useCallback(() => setFailed(true), []);
  const slow=useCallback(() => { if(low) setFailed(true); else setLow(true); },[low]);

  useEffect(() => {
    const compact=matchMedia("(max-width: 768px)"), reduced=matchMedia("(prefers-reduced-motion: reduce)");
    const probe=document.createElement("canvas");
    const gl=probe.getContext("webgl2");
    const supported=Boolean(gl);
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
    function update() {
      setEnvironment((previous) => ({ ...previous, ready:true, compact:compact.matches, reduced:reduced.matches, visible:document.visibilityState === "visible", supported }));
    }
    update();
    compact.addEventListener("change",update); reduced.addEventListener("change",update);
    document.addEventListener("visibilitychange",update);
    const observer=new IntersectionObserver(([entry]) => setEnvironment((previous) => ({...previous,onscreen:entry.isIntersecting})));
    if(holder.current) observer.observe(holder.current);
    return () => {
      compact.removeEventListener("change",update); reduced.removeEventListener("change",update);
      document.removeEventListener("visibilitychange",update); observer.disconnect();
    };
  }, []);

  useEffect(() => {
    const target=holder.current;
    function contextLost(event: Event) { event.preventDefault(); setFailed(true); }
    target?.addEventListener("webglcontextlost",contextLost,true);
    return () => target?.removeEventListener("webglcontextlost",contextLost,true);
  }, []);

  const motion=enabled ?? !environment.reduced;
  const usable=environment.ready && environment.supported && !failed;
  const active=usable && motion && environment.visible && environment.onscreen;
  return <div className="entry-pitch" ref={holder} data-motion={motion ? "on" : "off"} data-scene-state={failed ? "fallback" : ready ? "ready" : "poster"}>
    {(!ready || !usable || !motion) && <PitchPoster />}
    {usable && (motion || ready) && <div className="entry-webgl" aria-hidden="true" style={{ visibility:ready && motion ? "visible" : "hidden" }}>
      <SceneBoundary onFailure={markFailed}>
        <Canvas orthographic camera={{position:[11,12,14],near:.1,far:80,zoom:40}} dpr={environment.compact || low ? 1 : [1,1.5]}
          frameloop="demand" gl={{alpha:true,antialias:!environment.compact,powerPreference:"low-power"}} fallback={null}>
          <PitchScene active={active} compact={environment.compact} low={low} onSlow={slow} onReady={markReady} />
        </Canvas>
      </SceneBoundary>
    </div>}
    <button className="entry-motion" aria-pressed={motion && usable} disabled={!environment.ready || !environment.supported || failed}
      onClick={() => setEnabled(!motion)}>{failed || (environment.ready && !environment.supported) ? "静态球场" : motion ? "暂停动画" : "开启动画"}<span aria-hidden="true">{motion && usable ? "Ⅱ" : "▷"}</span></button>
  </div>;
}

export default memo(PitchCanvas);
