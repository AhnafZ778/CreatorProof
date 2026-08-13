'use client';

import React, { useRef, useEffect, useCallback } from 'react';
import { gsap } from 'gsap';

interface LoopingWordsProps {
  words: string[];
}

export const LoopingWords: React.FC<LoopingWordsProps> = ({ words }) => {
  const wordListRef = useRef<HTMLUListElement>(null);
  const edgeElementRef = useRef<HTMLDivElement>(null);
  const timelineRef = useRef<gsap.core.Timeline | null>(null);

  // Duplicate words array once for seamless infinite loop
  const displayWords = [...words, ...words];
  const originalCount = words.length;
  const totalItems = displayWords.length;
  const currentStepRef = useRef<number>(0);

  const updateEdgeWidth = useCallback((step: number) => {
    const wordList = wordListRef.current;
    const edgeElement = edgeElementRef.current;
    if (!wordList || !edgeElement) return;

    const activeIndex = (step + 1) % totalItems;

    Array.from(wordList.children).forEach((child, idx) => {
      if (idx === activeIndex) {
        child.classList.add('is-active');
      } else {
        child.classList.remove('is-active');
      }
    });

    const activeWord = wordList.children[activeIndex] as HTMLLIElement;

    if (activeWord) {
      const pElement = activeWord.querySelector('.looping-words__p') || activeWord;
      const textWidth = pElement.getBoundingClientRect().width;
      const viewportWidth = document.documentElement.clientWidth;
      const targetWidth = Math.min(textWidth + 56, Math.max(240, viewportWidth - 32));

      gsap.to(edgeElement, {
        width: `${targetWidth}px`,
        duration: 0.5,
        ease: 'expo.out',
      });
    }
  }, [totalItems]);

  const moveWords = useCallback(() => {
    const wordList = wordListRef.current;
    if (!wordList) return;

    currentStepRef.current += 1;
    const step = currentStepRef.current;
    updateEdgeWidth(step);

    const firstChild = wordList.children[0] as HTMLElement;
    const itemHeight = firstChild ? firstChild.getBoundingClientRect().height : 75;

    gsap.to(wordList, {
      y: -step * itemHeight,
      duration: 1.2,
      ease: 'elastic.out(1, 0.85)',
      onComplete: function() {
        if (step >= originalCount) {
          currentStepRef.current = 0;
          gsap.set(wordList, { y: 0 });
          updateEdgeWidth(0);
        }
      },
    });
  }, [originalCount, updateEdgeWidth]);

  useEffect(() => {
    updateEdgeWidth(0);
    timelineRef.current = gsap.timeline({ repeat: -1, delay: 1 });
    timelineRef.current
      .call(moveWords)
      .to({}, { duration: 2.2 });

    return () => {
      if (timelineRef.current) {
        timelineRef.current.kill();
      }
    };
  }, [moveWords, updateEdgeWidth]);

  return (
    <div className="relative overflow-hidden py-8 max-w-4xl mx-auto">
      <div className="looping-words relative h-[225px] block overflow-hidden [mask-image:linear-gradient(to_bottom,transparent_0%,black_25%,black_75%,transparent_100%)] [-webkit-mask-image:linear-gradient(to_bottom,transparent_0%,black_25%,black_75%,transparent_100%)]">
        <div className="looping-words__containers absolute top-0 left-0 w-full h-full flex justify-center z-10">
          <ul data-looping-words-list="" className="looping-words__list absolute top-0 flex flex-col items-center margin-0 padding-0 list-none" ref={wordListRef}>
            {displayWords.map((word, index) => (
              <li key={index} className="looping-words__list flex items-center justify-center h-[75px] text-xl sm:text-2xl font-semibold tracking-tight text-white px-7 whitespace-nowrap box-border opacity-35 transition-opacity duration-400 [&.is-active]:opacity-100">
                <p className="looping-words__p m-0 text-[clamp(0.75rem,3.6vw,1.25rem)] sm:text-2xl text-white drop-shadow-[0_0_25px_rgba(255,255,255,0.7)]">{word}</p>
              </li>
            ))}
          </ul>
        </div>
        <div data-looping-words-selector="" className="looping-words__selector absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 h-[65px] border border-white/85 rounded-2xl bg-gradient-to-br from-white/15 to-white/5 backdrop-blur-xl transition-all z-0 flex items-center justify-between px-2 shadow-[0_0_30px_rgba(255,255,255,0.25),0_0_60px_rgba(56,189,248,0.3),inset_0_0_25px_rgba(255,255,255,0.12)] pointer-events-none" ref={edgeElementRef}>
          <div className="looping-words__edge absolute -top-1 -left-1 w-3.5 h-3.5 border-t-2 border-l-2 border-white filter drop-shadow-[0_0_6px_rgba(255,255,255,0.8)]"></div>
          <div className="looping-words__edge is--2 absolute -top-1 -right-1 w-3.5 h-3.5 border-t-2 border-r-2 border-white filter drop-shadow-[0_0_6px_rgba(255,255,255,0.8)]"></div>
          <div className="looping-words__edge is--3 absolute -bottom-1 -left-1 w-3.5 h-3.5 border-b-2 border-l-2 border-white filter drop-shadow-[0_0_6px_rgba(255,255,255,0.8)]"></div>
          <div className="looping-words__edge is--4 absolute -bottom-1 -right-1 w-3.5 h-3.5 border-b-2 border-r-2 border-white filter drop-shadow-[0_0_6px_rgba(255,255,255,0.8)]"></div>
        </div>
      </div>
    </div>
  );
};
