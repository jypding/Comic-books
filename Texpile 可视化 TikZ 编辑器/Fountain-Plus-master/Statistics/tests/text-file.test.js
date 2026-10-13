import { describe, test, expect } from 'bun:test';
import { computeTextFileStatistics } from '../index.js';

describe('computeTextFileStatistics', () =>
{
    test('empty string -> all zero', () =>
    {
        expect(computeTextFileStatistics('')).toEqual(
            { words: 0, characters: 0, lines: 0, spaces: 0, tabs: 0 }
        );
    });

    test('non-string input -> all zero', () =>
    {
        // @ts-expect-error runtime guard
        expect(computeTextFileStatistics(null)).toEqual(
            { words: 0, characters: 0, lines: 0, spaces: 0, tabs: 0 }
        );
        // @ts-expect-error runtime guard
        expect(computeTextFileStatistics(undefined)).toEqual(
            { words: 0, characters: 0, lines: 0, spaces: 0, tabs: 0 }
        );
    });

    test('single line, no trailing newline -> 1 line', () =>
    {
        const s = computeTextFileStatistics('hello world');
        expect(s.words).toBe(2);
        expect(s.characters).toBe(11);
        expect(s.lines).toBe(1);
        expect(s.spaces).toBe(1);
        expect(s.tabs).toBe(0);
    });

    test('trailing newline yields extra line', () =>
    {
        expect(computeTextFileStatistics('abc\n').lines).toBe(2);
    });

    test('CRLF counts once per line-break pair', () =>
    {
        const s = computeTextFileStatistics('a\r\nb\r\nc');
        expect(s.lines).toBe(3);
    });

    test('bare CR counts as a line break', () =>
    {
        expect(computeTextFileStatistics('a\rb').lines).toBe(2);
    });

    test('tabs and spaces counted separately', () =>
    {
        const s = computeTextFileStatistics('a\tb c\td');
        expect(s.tabs).toBe(2);
        expect(s.spaces).toBe(1);
    });

    test('emoji cluster counts as one character (grapheme)', () =>
    {
        // 👨‍👩‍👧 = 1 grapheme, 8 UTF-16 code units
        const s = computeTextFileStatistics('👨‍👩‍👧');
        expect(s.characters).toBe(1);
    });

    test('CJK words segmented individually', () =>
    {
        // Intl.Segmenter with granularity: 'word' segments CJK by word;
        // exact count is locale-heuristic but must be >= 1.
        const s = computeTextFileStatistics('こんにちは世界');
        expect(s.words).toBeGreaterThanOrEqual(1);
    });
});
