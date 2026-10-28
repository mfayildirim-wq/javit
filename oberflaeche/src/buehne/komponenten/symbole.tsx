// Material-Symbols-Namen → Lucide-Symbole (bereits Abhängigkeit); unbekannt → Punkt.
import {
  ArrowLeft, ArrowRight, Bell, Calendar, Check, Clock, Cloud, CloudRain, Download, Droplets, Euro, ExternalLink, Heart, House, Info,
  Mail, MapPin, Pencil, Phone, Plus, Search, Settings, Share2, Star, StickyNote, Sun, Thermometer, Trash2, TriangleAlert, Upload, User, Wind, X,
  type LucideIcon,
} from 'lucide-react';

const SYMBOLE: Record<string, LucideIcon> = {
  home: House,
  house: House,
  mail: Mail,
  email: Mail,
  cloud: Cloud,
  rain: CloudRain,
  rainy: CloudRain,
  sunny: Sun,
  sun: Sun,
  star: Star,
  edit: Pencil,
  delete: Trash2,
  search: Search,
  person: User,
  place: MapPin,
  location_on: MapPin,
  calendar: Calendar,
  calendar_today: Calendar,
  event: Calendar,
  check: Check,
  done: Check,
  warning: TriangleAlert,
  info: Info,
  phone: Phone,
  call: Phone,
  euro: Euro,
  euro_symbol: Euro,
  arrow: ArrowRight,
  arrow_forward: ArrowRight,
  arrow_back: ArrowLeft,
  schedule: Clock,
  open_in_new: ExternalLink,
  note: StickyNote,
  add: Plus,
  close: X,
  favorite: Heart,
  notifications: Bell,
  settings: Settings,
  download: Download,
  upload: Upload,
  share: Share2,
  thermostat: Thermometer,
  air: Wind,
  water_drop: Droplets,
};

export function Symbolbild({ name, groesse = 16 }: { name: unknown; groesse?: number }) {
  const S = typeof name === 'string' ? SYMBOLE[name.trim().toLowerCase()] : undefined;
  if (!S) return <span aria-hidden="true">•</span>;
  return <S size={groesse} aria-hidden="true" strokeWidth={1.8} />;
}
