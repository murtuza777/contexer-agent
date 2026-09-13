import React from "react";
import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";
import { Hero } from "@/components/sections/Hero";
import { ProblemDifference } from "@/components/sections/ProblemDifference";
import { CoreLoop } from "@/components/sections/CoreLoop";
import { AutonomousVerification } from "@/components/sections/AutonomousVerification";
import { Architecture } from "@/components/sections/Architecture";
import { AgentAgnostic } from "@/components/sections/AgentAgnostic";
import { DevExperience } from "@/components/sections/DevExperience";
import { OpenSource } from "@/components/sections/OpenSource";
import { DownloadSection } from "@/components/sections/DownloadSection";
import { FinalCta } from "@/components/sections/FinalCta";

export default function Home() {
  return (
    <div className="min-h-screen flex flex-col bg-[#08090d] text-[#f4f4f5] selection:bg-cyan-500/20 selection:text-cyan-300">
      <Navbar />

      <main className="flex-1">
        <Hero />
        <ProblemDifference />
        <CoreLoop />
        <AutonomousVerification />
        <Architecture />
        <AgentAgnostic />
        <DevExperience />
        <OpenSource />
        <DownloadSection />
        <FinalCta />
      </main>

      <Footer />
    </div>
  );
}
