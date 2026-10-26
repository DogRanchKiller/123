"use client";

import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import { AdditiveBlending, type Group, type OrthographicCamera, type ShaderMaterial } from "three";

const cyan = "#5dfff0";
type Point = [number, number, number];
const rect = (x: number, z: number, w: number, h: number, y = .065): Point[] => [[x,y,z],[x+w,y,z],[x+w,y,z+h],[x,y,z+h],[x,y,z]];
const circle = (radius: number): Point[] => Array.from({ length: 65 }, (_, i) => [Math.cos(i / 64 * Math.PI * 2) * radius, .07, Math.sin(i / 64 * Math.PI * 2) * radius]);
const fieldLines: Point[][] = [
  rect(-5.25,-3.4,10.5,6.8), [[0,.07,-3.4],[0,.07,3.4]], circle(.915),
  rect(-5.25,-2.016,1.65,4.032), rect(3.6,-2.016,1.65,4.032),
  rect(-5.25,-.916,.55,1.832), rect(4.7,-.916,.55,1.832),
];

function Field() {
  return <>
    <mesh position={[0,-.4,0]}><boxGeometry args={[11.25,.65,7.55]} /><meshStandardMaterial color="#082638" metalness={.65} roughness={.3} /></mesh>
    <mesh position={[0,-.045,0]}><boxGeometry args={[10.5,.15,6.8]} /><meshStandardMaterial color="#075655" metalness={.3} roughness={.48} /></mesh>
    {Array.from({ length: 10 }, (_, i) => <mesh key={i} rotation={[-Math.PI / 2,0,0]} position={[-4.725+i*1.05,.035,0]}>
      <planeGeometry args={[1.05,6.8]} /><meshBasicMaterial color={i % 2 ? "#0b6661" : "#075655"} transparent opacity={.65} />
    </mesh>)}
    {fieldLines.map((points,i) => <Line key={i} points={points} color={cyan} lineWidth={i === 0 ? 2 : 1} transparent opacity={i === 0 ? .95 : .65} toneMapped={false} />)}
    <Line points={rect(-5.62,-3.77,11.24,7.54,-.55)} color="#14c8c0" lineWidth={1} transparent opacity={.4} />
    {[-1,1].map((side) => <group key={side} position={[side*5.25,.05,0]}>
      <Line points={[[0,0,-.366],[0,.45,-.366],[0,.45,.366],[0,0,.366]]} color={cyan} lineWidth={1.4} />
      <Line points={[[0,.45,-.366],[side*.3,.32,-.366],[side*.3,.32,.366],[0,.45,.366]]} color={cyan} transparent opacity={.4} />
      <Line points={[[side*.3,.32,-.366],[side*.3,0,-.366],[side*.3,0,.366],[side*.3,.32,.366]]} color={cyan} transparent opacity={.3} />
    </group>)}
    {Array.from({length: 16}, (_,i) => {
      const x = (i % 4 - 1.5)*2.1, z = (Math.floor(i/4)-1.5)*1.55;
      return <group key={i} position={[x,.08,z]}>
        <mesh position={[0,.14,0]}><cylinderGeometry args={[.016,.045,.28,6]} /><meshBasicMaterial color={cyan} transparent opacity={.5} /></mesh>
        <mesh position={[0,.32,0]}><sphereGeometry args={[.044,8,8]} /><meshBasicMaterial color={cyan} toneMapped={false} /></mesh>
        <mesh rotation={[-Math.PI/2,0,0]}><ringGeometry args={[.08,.095,20]} /><meshBasicMaterial color={cyan} transparent opacity={.45} /></mesh>
      </group>;
    })}
    {[-1,1].map((side) => <Line key={side} points={Array.from({length: 31}, (_,i): Point => {
      const t=i/30; return [-3.5+t*7,.08+Math.sin(t*Math.PI)*.6,side*(1.1+Math.sin(t*Math.PI*2)*.5)];
    })} color="#6affdc" transparent opacity={.26} dashed dashSize={.12} gapSize={.15} lineWidth={1} />)}
  </>;
}

const particleVertex = `
  uniform float time; uniform float gather; attribute float seed;
  varying float alpha;
  void main() {
    vec3 p = position;
    p.y += sin(time * .32 + seed * 24.) * .38;
    p.x += sin(time * .13 + seed * 40.) * .2;
    p.xz *= 1. + (1. - gather) * .7;
    alpha = (.25 + .5 * sin(seed * 150. + time * .5) * sin(seed * 150. + time * .5)) * gather;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.);
    gl_PointSize = 1.2 + seed * 2.4;
  }`;
const particleFragment = `
  varying float alpha;
  void main() {
    float d = length(gl_PointCoord - .5);
    if (d > .5) discard;
    gl_FragColor = vec4(.18, 1., .86, alpha * smoothstep(.5, .05, d));
  }`;

function Particles({ count, clock }: { count: number; clock: { current: number } }) {
  const material = useRef<ShaderMaterial>(null);
  const data = useMemo(() => {
    // 确定性分布仅用于装饰粒子，与预测字段完全隔离。
    const positions = new Float32Array(count*3), seeds = new Float32Array(count);
    const fraction = (n: number) => { const v = Math.sin(n*127.1)*43758.5453; return v-Math.floor(v); };
    for (let i=0;i<count;i++) {
      positions[i*3]=(fraction(i+1)-.5)*20;
      positions[i*3+1]=fraction(i+500)*5-.8;
      positions[i*3+2]=(fraction(i+1000)-.5)*15;
      seeds[i]=fraction(i+1500);
    }
    return { positions, seeds };
  }, [count]);
  const uniforms = useMemo(() => ({ time: {value: 0}, gather: {value: 0} }), []);
  useFrame(() => {
    if (!material.current) return;
    material.current.uniforms.time.value=clock.current;
    material.current.uniforms.gather.value=Math.min(1,clock.current/1.5);
  });
  return <points frustumCulled={false}>
    <bufferGeometry>
      <bufferAttribute attach="attributes-position" args={[data.positions,3]} />
      <bufferAttribute attach="attributes-seed" args={[data.seeds,1]} />
    </bufferGeometry>
    <shaderMaterial ref={material} uniforms={uniforms} vertexShader={particleVertex} fragmentShader={particleFragment} transparent depthWrite={false} blending={AdditiveBlending} />
  </points>;
}

export function PitchScene({ active, compact, low, onSlow, onReady }: {
  active: boolean; compact: boolean; low: boolean; onSlow: () => void; onReady: () => void;
}) {
  const field = useRef<Group>(null), scan = useRef<Group>(null);
  const time = useRef(0);
  const pointer = useRef({ x: 0, y: 0 });
  const sample = useRef({ duration: 0, frames: 0 });
  const { camera, size, invalidate } = useThree();
  useEffect(() => {
    if (!active || compact) return;
    const move = (event: PointerEvent) => {
      pointer.current = { x: event.clientX / innerWidth * 2 - 1, y: 1 - event.clientY / innerHeight * 2 };
    };
    window.addEventListener("pointermove", move, { passive: true });
    return () => window.removeEventListener("pointermove", move);
  }, [active, compact]);
  useEffect(() => {
    const ortho = camera as OrthographicCamera;
    // R3F 的命令式相机必须在 effect 中更新投影。
    // eslint-disable-next-line react-hooks/immutability
    ortho.zoom=Math.min(size.width/17.5,size.height/13.8);
    ortho.lookAt(0,0,0);
    ortho.updateProjectionMatrix();
    invalidate();
  }, [camera,size.width,size.height,invalidate]);
  useEffect(() => {
    if (!active) return;
    let frame=0, last=0;
    function tick(now: number) {
      if (now-last >= (compact ? 1000/30 : 1000/60)-1) { invalidate(); last=now; }
      frame=requestAnimationFrame(tick);
    }
    frame=requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [active,compact,invalidate]);
  useEffect(() => { onReady(); }, [onReady]);
  useFrame((_,delta) => {
    if (!active) return;
    const step=Math.min(delta,.1);
    time.current+=step;
    const t=time.current, intro=1-Math.pow(1-Math.min(1,t/1.5),3);
    if (field.current) {
      field.current.position.y= Math.sin(t*.45)*.075-(1-intro)*.8;
      field.current.scale.setScalar(.94+intro*.06);
      field.current.rotation.y+=(pointer.current.x*.025-field.current.rotation.y)*.025;
      field.current.rotation.z+=(pointer.current.y*.012-field.current.rotation.z)*.025;
    }
    if(scan.current) scan.current.position.x=-5.1+((t*.55)%10.2);
    if (delta < .3 && t > 3) {
      sample.current.duration+=delta; sample.current.frames++;
      if(sample.current.duration >= 3) {
        if(sample.current.frames/sample.current.duration < (low ? 18 : 24)) onSlow();
        sample.current={duration:0,frames:0};
      }
    }
  });
  return <>
    <ambientLight intensity={1.3} /><directionalLight position={[4,8,3]} intensity={2} color="#96fff0" />
    <pointLight position={[-3,3,-3]} intensity={18} color="#087ed5" />
    <fog attach="fog" args={["#031018",18,40]} />
    <gridHelper args={[30,30,"#12515a","#0a2a34"]} position={[0,-.92,0]} />
    <group ref={field}>
      <Field />
      <group ref={scan}><mesh position={[0,.075,0]} rotation={[-Math.PI/2,0,0]}><planeGeometry args={[.14,6.75]} /><meshBasicMaterial color={cyan} transparent opacity={.3} toneMapped={false} depthWrite={false} /></mesh></group>
    </group>
    <Particles count={compact ? 800 : low ? 1500 : 3000} clock={time} />
    {!compact && !low && <EffectComposer multisampling={0}><Bloom luminanceThreshold={.75} intensity={.7} mipmapBlur /></EffectComposer>}
  </>;
}
