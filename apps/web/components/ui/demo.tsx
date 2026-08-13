import { Globe } from "@/components/ui/globe"

export function GlobeDemo() {
  return (
    <div className="relative flex size-full max-w-lg items-center justify-center overflow-hidden rounded-lg border border-white/10 bg-black/40 px-40 pb-40 pt-8 md:pb-60 md:shadow-xl backdrop-blur-xl">
      <span className="pointer-events-none whitespace-pre-wrap bg-gradient-to-b from-white to-gray-400/80 bg-clip-text text-center text-8xl font-semibold leading-none text-transparent">
        Globe
      </span>
      <Globe className="top-28" />
      <div className="pointer-events-none absolute inset-0 h-full bg-[radial-gradient(circle_at_50%_200%,rgba(0,0,0,0.4),rgba(255,255,255,0))]" />
    </div>
  )
}
