import type { ComponentPropsWithRef, FC } from 'react';
import { cx } from '../../utils/cx';
import styles from './AudioPlayer.module.css';

type IAudioPlayerProps = Omit<ComponentPropsWithRef<'audio'>, 'controls'>;

/** Нативный `<audio controls>` с общим оформлением; остальные пропсы (ref, src, preload, события) — как у audio. */
export const AudioPlayer: FC<IAudioPlayerProps> = ({ className, ...rest }) => (
  <audio controls className={cx(styles.audio, className)} {...rest} />
);
