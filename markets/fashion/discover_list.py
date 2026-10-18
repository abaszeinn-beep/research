import json
U="""Splash|https://www.splashfashions.com/qa/en
Splash|https://www.splashfashions.com/qa/
Styli|https://stylishop.com/qa/en
Lifestyle|https://www.lifestylestores.com/qa/en
Centrepoint|https://www.centrepointstores.com/qa/en
Babyshop|https://www.babyshopstores.com/qa/en
Max Fashion|https://www.maxfashion.com/qa/en
Home Centre|https://www.homecentre.com/qa/en
Sun & Sand Sports|https://www.sunandsandsports.com/qa/en
Brands For Less|https://www.brandsforless.com/en-qa/
Brands For Less|https://www.brandsforless.com/ar-qa/
Namshi|https://www.namshi.com/qatar-en/
6thStreet|https://en-qa.6thstreet.com/
6thStreet|https://en-qa.aivi.com/
Ounass|https://www.ounass.qa/
Level Shoes|https://www.levelshoes.com/qa/
Farfetch|https://www.farfetch.com/qa/
Mamas & Papas|https://www.mamasandpapas.qa/
Tommy Hilfiger|https://qa.tommy.com/
Tommy Hilfiger|https://qa.tommy.com/en
Calvin Klein|https://www.calvinklein.qa/
Calvin Klein|https://qa.calvinklein.com/
Guess|https://www.guess.eu/en
Guess|https://www.guess.qa/
Lacoste|https://www.lacoste.com/qa/
Lacoste|https://www.lacoste.qa/
Puma|https://qa.puma.com/
Puma|https://qa.puma.com/qa/en
Reebok|https://www.reebok.qa/
Skechers|https://www.skechers.qa/
Decathlon|https://www.decathlon.qa/
Decathlon|https://www.decathlon.qa/en
Under Armour|https://www.underarmour.qa/
Under Armour|https://www.underarmour.ae/
New Balance|https://www.newbalance.qa/
Columbia|https://www.columbiasportswear.qa/
The North Face|https://www.thenorthface.qa/
Timberland|https://www.timberland.qa/
Levi's|https://www.levi.qa/
Levi's|https://qa.levi.com/
Marks & Spencer|https://www.marksandspencer.qa/
Marks & Spencer|https://www.marksandspencer.com/ar-qa
Marks & Spencer|https://www.marksandspencer.com/qa
Debenhams|https://www.debenhams.qa/
Debenhams|https://www.debenhams.com/qa
Hollister|https://www.hollisterco.com/qa/en
Abercrombie|https://www.abercrombie.com/qa/en
American Eagle|https://www.americaneagle.com.qa/
Victoria's Secret|https://www.victoriassecret.com.qa/
Bath & Body Works|https://www.bathandbodyworks.qa/
Aldo|https://www.aldoshoes.qa/
Charles & Keith|https://www.charleskeith.com/qa
Pull&Bear|https://www.pullandbear.com/qa/
Zara|https://www.zara.com/qa/en/
Zara Home|https://www.zarahome.com/qa/
Bershka|https://www.bershka.com/qa/
Stradivarius|https://www.stradivarius.com/qa/
Oysho|https://www.oysho.com/qa/
Massimo Dutti|https://www.massimodutti.com/qa/
Mango|https://shop.mango.com/qa/
H&M|https://qa.hm.com/
H&M|https://www2.hm.com/en_qa/
H&M|https://www2.hm.com/ar_qa/
Next|https://www.next.qa/
Next|https://www.next.com.qa/
Gap|https://www.gap.qa/
Gap|https://gap.com.qa/
Gap|https://www.gap.me/
Marks Spencer|https://www.marksandspencer.me/
River Island|https://www.riverisland.qa/
Uniqlo|https://www.uniqlo.com/qa/
Uniqlo|https://www.uniqlo.com/qa/en/
LC Waikiki|https://www.lcwaikiki.qa/
LC Waikiki|https://www.lcw.com/qa
DeFacto|https://www.defacto.com/en-qa
DeFacto|https://www.defacto.com/ar-qa
Koton|https://www.koton.com/en-qa/
Koton|https://www.koton.com/qa/
Forever 21|https://www.forever21.com/qa/
New Look|https://www.newlook.qa/
Nike|https://www.nike.qa/
Adidas|https://www.adidas.qa/
Jack & Jones|https://www.jackjones.com/qa/
Vero Moda|https://www.veromoda.com/qa/
Only|https://www.only.com/qa/
Hugo Boss|https://www.hugoboss.com/qa/
Michael Kors|https://www.michaelkors.global/qa/
Mothercare|https://www.mothercare.qa/
Aeropostale|https://www.aeropostale.qa/
Esprit|https://www.esprit.qa/
Springfield|https://www.springfield.com/qa/
Women'secret|https://www.womensecret.com/qa/
Women'secret|https://womensecret.com/qa/en/
Intimissimi|https://www.intimissimi.com/qa/
Calzedonia|https://www.calzedonia.com/qa/
Tezenis|https://www.tezenis.com/qa/
Triumph|https://www.triumph.com/qa/
Sloggi|https://www.sloggi.com/qa/
Jockey|https://www.jockey.qa/
Cotton On|https://cottonon.com/qa/
Dune|https://www.dunelondon.qa/
Ted Baker|https://www.tedbaker.com/qa
Sandro|https://qa.sandro-paris.com/
Maje|https://qa.maje.com/
The Kooples|https://www.thekooples.com/qa
Karl Lagerfeld|https://www.karl.com/qa
Armani Exchange|https://www.armaniexchange.com/qa
Emporio Armani|https://www.armani.com/en-qa
Gucci|https://www.gucci.com/qa/en/
Prada|https://www.prada.com/qa/en.html
Dior|https://www.dior.com/en_qa
Burberry|https://qa.burberry.com/
Fendi|https://www.fendi.com/qa-en
Balenciaga|https://www.balenciaga.com/en-qa
Saint Laurent|https://www.ysl.com/en-qa
Valentino|https://www.valentino.com/en-qa/
Versace|https://www.versace.com/qa/en/
Dolce & Gabbana|https://www.dolcegabbana.com/en-qa/
Louis Vuitton|https://qa.louisvuitton.com/
Hermes|https://www.hermes.com/qa/en/
Moncler|https://www.moncler.com/en-qa
Zegna|https://www.zegna.com/qa-en/
Loro Piana|https://www.loropiana.com/en-qa
Brunello Cucinelli|https://shop.brunellocucinelli.com/en-qa
Ralph Lauren|https://www.ralphlauren.qa/
Ralph Lauren|https://qa.ralphlauren.com/
Lululemon|https://www.lululemon.qa/
Gymshark|https://row.gymshark.com/
Hunkemoller|https://www.hunkemoller.qa/
Pepe Jeans|https://www.pepejeans.qa/
Diesel|https://qa.diesel.com/
Superdry|https://www.superdry.qa/
Bossini|https://www.bossini.qa/
Bonia|https://www.bonia.qa/
Jaded London|https://www.jadedldn.com/
Cheapsmokes|https://example.invalid/
Tresemme|https://example.invalid/
Dar Al Abaya|https://daralabaya.com/
Dar Al Abaya|https://daralabaya.qa/
Hayaa Abaya|https://www.hayaaabaya.com/
Rwaj|https://rwaj.co
Abayat Qatar|https://abayat.qa/
Mirzam|https://mirzam.qa/
Al Motahajiba|https://almotahajiba.com/
Vogacloset|https://vogacloset.com/qatar/
Vogacloset|https://www.vogacloset.com/
Modanisa|https://www.modanisa.com/ar/
Modanisa|https://modanisa.com/
Nayomi|https://nayomi.com/qa-en
Nayomi|https://nayomi.com/
Zaful|https://qa.zaful.com/
Shein|https://m.shein.com/qa-en/
Shein|https://ar.shein.com/
Romwe|https://www.romwe.com/
Cider|https://www.shopcider.com/
Fashion Nova|https://www.fashionnova.com/
ASOS|https://www.asos.com/
PrettyLittleThing|https://www.prettylittlething.com/
Boohoo|https://www.boohoo.com/
Lulu Hypermarket|https://gcc.luluhypermarket.com/en-qa/
Carrefour|https://www.carrefourqatar.com/
Carrefour|https://www.carrefourqatar.com/mafqat/en/
Monoprix|https://www.monoprixqatar.com/
Megamart|https://www.megamart.qa/
Safari Hypermarket|https://safarihypermarket.com/
Family Food Centre|https://www.familyfoodcentre.com/
Ansar Gallery|https://www.ansargallery.com/
Al Meera|https://www.almeera.com.qa/
Souq Al Baladi|https://www.souqalbaladi.com/
Rawabi Hypermarket|https://www.rawabihypermarket.qa/
Aamal|https://example.invalid/
Jarir Qatar|https://www.jarir.com/qa-en/
Virgin Megastore|https://www.virginmegastore.qa/
Virgin Megastore|https://www.virginmegastore.me/qa/en
Centrepoint|https://www.centrepointstores.com/qa/en/
Alshaya|https://www.alshaya.com/
Level Kids|https://www.levelkids.com/qa/
Harvey Nichols|https://www.harveynichols.com/qa/
Galeries Lafayette|https://www.galerieslafayette.qa/
Rivoli|https://www.rivoli.qa/
Villa Moda|https://www.villamoda.com/
Bloomingdale's|https://www.bloomingdales.qa/
Bloomingdale's|https://www.bloomingdales.ae/
Saks|https://www.saks.com/
Vacation Lovers|https://example.invalid/
Alo Yoga|https://www.aloyoga.com/
Nine West|https://www.ninewest.qa/
Ecco|https://www.ecco.com/qa
Crocs|https://www.crocs.qa/
Fila|https://www.fila.qa/
Fila|https://www.fila.com/qa
Asics|https://www.asics.com/qa/en-qa/
Hoka|https://www.hoka.com/en/qa/
Converse|https://www.converse.qa/
Vans|https://www.vans.qa/
Champion|https://www.champion.qa/
Kappa|https://www.kappa.qa/
Umbro|https://www.umbro.qa/
Mizuno|https://www.mizuno.qa/
Speedo|https://www.speedo.qa/
Arena|https://www.arenasport.qa/
Hush Puppies|https://www.hushpuppies.qa/
Tom Tailor|https://www.tom-tailor.qa/
Camel Active|https://www.camelactive.qa/
Pierre Cardin|https://www.pierrecardin.qa/
Cavalli Class|https://www.robertocavalli.com/qa
Celio|https://www.celio.qa/
Celio|https://www.celio.com/qa
Jules|https://www.jules.qa/
Sfera|https://www.sfera.com/qa/
Lefties|https://www.lefties.com/qa/
Mayoral|https://www.mayoral.com/qa
Okaidi|https://www.okaidi.qa/
Zippy|https://www.zippy.qa/
Dockers|https://www.dockers.qa/
Wrangler|https://www.wrangler.qa/
Lee|https://www.lee.qa/
Replay|https://www.replayjeans.qa/
Mexx|https://www.mexx.qa/
OVS|https://www.ovs.qa/
OVS|https://www.ovsfashion.com/qa
Terranova|https://www.terranovastyle.com/qa
Max Mara|https://www.maxmara.com/qa
Max&Co|https://www.maxandco.com/qa
Zeen|https://example.invalid/"""
out=[];seen=set()
for l in U.splitlines():
    n,u=l.split('|')
    if 'invalid' in u or u in seen: continue
    seen.add(u); out.append({'key':'new:'+u,'name':n,'url':u})
json.dump(out,open('extra_urls.json','w'),indent=0); print(len(out))
