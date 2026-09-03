export interface VisionFrameCursor {
  epoch: number;
  frameId: number;
}

export class VisionLatestPollGuard {
  private generation = 0;
  private inFlight = false;
  private latest: VisionFrameCursor | null = null;

  reset(): void {
    this.generation += 1;
    this.inFlight = false;
    this.latest = null;
  }

  begin(): number | null {
    if (this.inFlight) return null;
    this.inFlight = true;
    return this.generation;
  }

  finish(token: number): void {
    if (token === this.generation) this.inFlight = false;
  }

  accept(token: number, candidate: VisionFrameCursor): boolean {
    if (token !== this.generation) return false;
    if (
      this.latest
      && (candidate.epoch < this.latest.epoch
        || (candidate.epoch === this.latest.epoch && candidate.frameId < this.latest.frameId))
    ) return false;
    this.latest = candidate;
    return true;
  }
}
