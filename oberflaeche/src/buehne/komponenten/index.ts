// Alle Bausteine des Katalogs jarvis:buehne/1 registrieren (22 Komponenten).
import { registrieren } from '../register';
import { Badge, Fortschritt, Icon, Image, Karte, Kennzahl } from './anzeige';
import { Button } from './Button';
import { Diagramm } from './Diagramm';
import { CheckBox, ChoicePicker, DateTimeInput, TextField } from './eingaben';
import { Formular } from './Formular';
import { Card, Column, Divider, Grid, List, Row, Tabs } from './layout';
import { Tabelle } from './Tabelle';
import { Text } from './Text';

export const KATALOG_BAUSTEINE = {
  Column, Row, Grid, Card, List, Tabs, Divider,
  Text, Image, Icon, Badge, Kennzahl, Fortschritt, Tabelle, Karte, Diagramm,
  Button, TextField, CheckBox, ChoicePicker, DateTimeInput, Formular,
};

registrieren(KATALOG_BAUSTEINE);
